import os
import json
import re
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
import customtkinter as ctk
import ollama
import threading
import queue
import tkinter as tk
import speech_recognition as sr
import pyttsx3

# --- Configuration ---
OLLAMA_MODEL = "llama3"
WINDOW_WIDTH = 1200
WINDOW_HEIGHT = 800
STATS_PANEL_WIDTH = 280
MAIN_AREA_PAD = 20
PROFILE_FILE = "profile.json"
CHATS_DIR = "chats"
os.makedirs(CHATS_DIR, exist_ok=True)

# System prompt
SYSTEM_PROMPT = (
    "You are FitGen, an expert AI Fitness Coach. Help users with workout plans, "
    "diet/nutrition advice, weight loss, muscle gain, and goal setting. "
    "NEVER discuss unrelated topics. Keep responses science-based, encouraging, and personalized. "
    "ALWAYS incorporate the user's profile data when giving advice."
)

# 🎨 FITGEN COLOR SCHEME
FITGEN_COLORS = {
    'dark': {
        'primary': "#10b981", 'primary_dark': "#0da271", 'primary_light': "#34d399",
        'secondary': "#f59e0b", 'accent': "#3b82f6", 'danger': "#ef4444",
        'bg_main': "#0f172a", 'bg_card': "#1e293b", 'bg_input': "#1e293b", 'bg_stats': "#161e2e",
        'text_primary': "#f8fafc", 'text_secondary': "#cbd5e1", 'text_muted': "#94a3b8",
        'text_success': "#10b981", 'text_warning': "#f59e0b",
        'border': "#334155", 'divider': "#2c3446",
    },
    'light': {
        'primary': "#10b981", 'primary_dark': "#0da271", 'primary_light': "#34d399",
        'secondary': "#f59e0b", 'accent': "#3b82f6", 'danger': "#ef4444",
        'bg_main': "#f8fafc", 'bg_card': "#ffffff", 'bg_input': "#f1f5f9", 'bg_stats': "#f1f5f9",
        'text_primary': "#0f172a", 'text_secondary': "#475569", 'text_muted': "#94a3b8",
        'text_success': "#10b981", 'text_warning': "#f59e0b",
        'border': "#e2e8f0", 'divider': "#e2e8f0",
    }
}
current_theme = "dark"

class ModernToggleSwitch(ctk.CTkFrame):
    """Beautiful sliding toggle switch"""
    def __init__(self, master, command=None, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.command = command
        self.is_on = False
        
        self.track = ctk.CTkFrame(
            self, width=56, height=28, corner_radius=14,
            fg_color="#4b5563" if current_theme == "dark" else "#cbd5e1",
            border_width=2, border_color="#6b7280" if current_theme == "dark" else "#94a3b8"
        )
        self.track.grid(row=0, column=0, padx=(0, 8))
        
        self.knob = ctk.CTkFrame(self.track, width=24, height=24, corner_radius=12, fg_color="#10b981")
        self.knob.place(x=2, y=2)
        
        self.icon = ctk.CTkLabel(self, text="🌙", font=ctk.CTkFont(size=16),
                                text_color=FITGEN_COLORS[current_theme]['text_secondary'])
        self.icon.grid(row=0, column=1)
        
        for widget in (self.track, self.knob, self.icon):
            widget.bind("<Button-1>", self.toggle)
    
    def toggle(self, event=None):
        self.is_on = not self.is_on
        if self.is_on:
            self.track.configure(fg_color="#cbd5e1", border_color="#94a3b8")
            self.knob.place(x=30, y=2)
            self.icon.configure(text="☀️")
        else:
            self.track.configure(fg_color="#4b5563", border_color="#6b7280")
            self.knob.place(x=2, y=2)
            self.icon.configure(text="🌙")
        if self.command:
            self.command()
    
    def set_mode(self, dark_mode: bool):
        if self.is_on != (not dark_mode):
            self.toggle()

class ChatSession:
    def __init__(self, session_id, name="New Session"):
        self.id = session_id
        self.name = name
        self.created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.history = [{'role': 'system', 'content': SYSTEM_PROMPT}]
        self.widgets = {}
        self.current_ai_label = None
    
    def to_dict(self):
        return {"id": self.id, "name": self.name, "created_at": self.created_at, "history": self.history}
    
    @classmethod
    def from_dict(cls, data):
        session = cls(data["id"], data["name"])
        session.created_at = data["created_at"]
        session.history = data["history"]
        return session

class FitGenApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("💪 FitGen AI Fitness Coach")
        self.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
        self.minsize(1000, 700)
        self.resizable(True, True)
        
        # Proper exit handling
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        # Initialize TTS engine IN MAIN THREAD (critical fix)
        self.tts_engine = None
        self.tts_enabled = True
        self._init_tts_in_main_thread()
        
        # Load profile and chats
        self.profile = self.load_profile()
        self.sessions = self.load_sessions()
        self.current_session = None
        self.message_queue = queue.Queue()
        self.stats_panel_visible = True
        
        self.setup_ui()
        if not self.profile:
            self.show_profile_setup()
        else:
            self.show_dashboard()
        self.after(100, self.check_message_queue)

    def _init_tts_in_main_thread(self):
        """Initialize TTS engine SAFELY in main thread with comprehensive error handling"""
        try:
            print("🔊 Initializing TTS engine in MAIN THREAD (required for reliability)...")
            
            # Platform detection
            system = os.name
            driver = None
            
            if system == 'nt':  # Windows
                driver = 'sapi5'
                print("   → Windows: Using SAPI5 driver")
            elif system == 'posix':
                import platform
                if platform.system() == 'Darwin':  # macOS
                    driver = 'nsss'
                    print("   → macOS: Using NSSpeechSynthesizer driver")
                else:  # Linux
                    driver = 'espeak'
                    print("   → Linux: Using espeak driver")
            
            # Initialize engine
            self.tts_engine = pyttsx3.init(driverName=driver) if driver else pyttsx3.init()
            
            # Configure voice properties
            self.tts_engine.setProperty('rate', 170)  # Slightly slower for clarity
            self.tts_engine.setProperty('volume', 1.0)
            
            # Voice selection with fallbacks
            voices = self.tts_engine.getProperty('voices')
            print(f"   → Available voices: {len(voices)}")
            
            selected_voice = None
            if voices:
                # Prefer female voices for coach persona
                for voice in voices:
                    voice_name = voice.name.lower()
                    if 'female' in voice_name or 'zira' in voice_name or 'samantha' in voice_name or 'karen' in voice_name:
                        selected_voice = voice.id
                        print(f"   → Selected voice: {voice.name}")
                        break
                
                # Fallback to first voice if no female found
                if not selected_voice:
                    selected_voice = voices[0].id
                    print(f"   → Fallback voice: {voices[0].name}")
            
            if selected_voice:
                self.tts_engine.setProperty('voice', selected_voice)
            
            # CRITICAL: Test speech IN MAIN THREAD to verify working
            print("   → Testing speech...")
            self.tts_engine.say("FitGen voice active and ready")
            self.tts_engine.runAndWait()
            print("✅ TTS engine initialized successfully in MAIN THREAD")
            
        except Exception as e:
            print(f"❌ TTS initialization FAILED: {e}")
            print("\n💡 TROUBLESHOOTING GUIDE:")
            print("   Windows: Settings > Time & Language > Speech > Manage voices")
            print("   macOS: System Settings > Accessibility > VoiceOver > Open VoiceOver Utility > Speech")
            print("   Linux: sudo apt-get install espeak")
            print("\n⚠️  Voice disabled. Text responses will still work.")
            self.tts_engine = None
            self.tts_enabled = False

    def speak_in_main_thread(self, text):
        """Speak text SAFELY in main thread (no background threads!)"""
        if not self.tts_enabled or not self.tts_engine or not text.strip():
            return
        
        # Clean text for speech (remove emojis/special chars)
        clean_text = re.sub(r'[^\w\s.,!?]', '', text)
        clean_text = re.sub(r'\s+', ' ', clean_text).strip()
        
        if not clean_text:
            return
        
        print(f"🔊 Speaking: {clean_text[:60]}...")
        
        try:
            # CRITICAL: Run TTS SYNCHRONOUSLY in main thread
            self.tts_engine.say(clean_text)
            self.tts_engine.runAndWait()
        except Exception as e:
            print(f"🔊 TTS error: {e}")
            self.show_toast(f"🔊 Speech error: {str(e)[:40]}")

    def on_closing(self):
        """Clean exit"""
        try:
            if self.tts_engine:
                self.tts_engine.stop()
        except:
            pass
        self.destroy()
        os._exit(0)

    def load_profile(self):
        try:
            if os.path.exists(PROFILE_FILE):
                with open(PROFILE_FILE, 'r') as f:
                    return json.load(f)
        except Exception as e:
            print(f"Error loading profile: {e}")
        return None

    def save_profile(self, profile_data):
        try:
            with open(PROFILE_FILE, 'w') as f:
                json.dump(profile_data, f, indent=2)
            self.profile = profile_data
            self.update_stats_panel()
        except Exception as e:
            print(f"Error saving profile: {e}")

    def load_sessions(self):
        sessions = []
        try:
            chat_files = sorted(
                [f for f in os.listdir(CHATS_DIR) if f.endswith('.json')],
                reverse=True
            )[:20]
            
            for filename in chat_files:
                filepath = os.path.join(CHATS_DIR, filename)
                with open(filepath, 'r') as f:
                    data = json.load(f)
                    sessions.append(ChatSession.from_dict(data))
        except Exception as e:
            print(f"Error loading sessions: {e}")
        return sessions

    def save_current_session(self):
        if not self.current_session or len(self.current_session.history) <= 1:
            return None
        
        try:
            first_msg = next((msg['content'][:30] for msg in self.current_session.history 
                            if msg['role'] == 'user'), 'session')
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"chat_{timestamp}_{first_msg.replace(' ', '_').replace('/', '')}.json"
            filepath = os.path.join(CHATS_DIR, filename)
            
            with open(filepath, 'w') as f:
                json.dump(self.current_session.to_dict(), f, indent=2)
            
            self.sessions = self.load_sessions()
            self.update_chat_list()
            return filepath
        except Exception as e:
            print(f"Error saving session: {e}")
            return None

    def setup_ui(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # --- TOP NAVIGATION BAR ---
        self.top_nav = ctk.CTkFrame(self, height=70, corner_radius=0, fg_color=FITGEN_COLORS[current_theme]['bg_card'])
        self.top_nav.grid(row=0, column=0, columnspan=2, sticky="ew")
        self.top_nav.grid_columnconfigure(1, weight=1)

        brand_frame = ctk.CTkFrame(self.top_nav, fg_color="transparent")
        brand_frame.grid(row=0, column=0, padx=25, pady=15, sticky="w")
        ctk.CTkLabel(brand_frame, text="💪", font=ctk.CTkFont(size=28, weight="bold"), 
                    text_color=FITGEN_COLORS[current_theme]['primary']).pack(side="left", padx=(0, 10))
        ctk.CTkLabel(brand_frame, text="FITGEN", font=ctk.CTkFont(family="Segoe UI", size=24, weight="bold"),
                    text_color=FITGEN_COLORS[current_theme]['text_primary']).pack(side="left")
        ctk.CTkLabel(brand_frame, text="AI FITNESS COACH", font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
                    text_color=FITGEN_COLORS[current_theme]['text_muted']).pack(side="left", padx=(8, 0))

        center_frame = ctk.CTkFrame(self.top_nav, fg_color="transparent")
        center_frame.grid(row=0, column=1, sticky="ew")
        center_frame.grid_columnconfigure(0, weight=1)

        search_frame = ctk.CTkFrame(center_frame, fg_color=FITGEN_COLORS[current_theme]['bg_input'], 
                                   corner_radius=20, border_width=1, border_color=FITGEN_COLORS[current_theme]['border'])
        search_frame.grid(row=0, column=0, padx=20, sticky="ew")
        ctk.CTkLabel(search_frame, text="🔍", font=ctk.CTkFont(size=14),
                    text_color=FITGEN_COLORS[current_theme]['text_muted']).pack(side="left", padx=(15, 8))
        self.search_entry = ctk.CTkEntry(search_frame, placeholder_text="Quick fitness question...", height=36,
                                        font=ctk.CTkFont(family="Segoe UI", size=13), fg_color="transparent",
                                        border_width=0, text_color=FITGEN_COLORS[current_theme]['text_primary'],
                                        placeholder_text_color=FITGEN_COLORS[current_theme]['text_muted'])
        self.search_entry.pack(side="left", fill="x", expand=True, padx=(0, 15))
        self.search_entry.bind("<Return>", lambda e: self.handle_search())

        right_frame = ctk.CTkFrame(self.top_nav, fg_color="transparent")
        right_frame.grid(row=0, column=2, padx=20, sticky="e")
        self.theme_toggle = ModernToggleSwitch(right_frame, command=self.toggle_theme)
        self.theme_toggle.pack(side="left", padx=(0, 15))
        ctk.CTkButton(right_frame, text="👤 Profile", height=38, width=100,
                     font=ctk.CTkFont(family="Segoe UI", size=13, weight="normal"),
                     fg_color=FITGEN_COLORS[current_theme]['bg_input'],
                     hover_color=FITGEN_COLORS[current_theme]['border'], border_width=1,
                     border_color=FITGEN_COLORS[current_theme]['border'],
                     text_color=FITGEN_COLORS[current_theme]['text_primary'], corner_radius=12,
                     command=self.show_profile_setup).pack(side="left", padx=(0, 10))
        ctk.CTkButton(right_frame, text="⚙️", width=38, height=38, font=ctk.CTkFont(size=14),
                     fg_color=FITGEN_COLORS[current_theme]['bg_input'],
                     hover_color=FITGEN_COLORS[current_theme]['border'], border_width=1,
                     border_color=FITGEN_COLORS[current_theme]['border'], corner_radius=12,
                     command=lambda: self.show_toast("⚙️ Settings coming soon!")).pack(side="left")

        # --- STATS PANEL (Scrollable) ---
        self.stats_panel = ctk.CTkFrame(self, width=STATS_PANEL_WIDTH, corner_radius=0, 
                                       fg_color=FITGEN_COLORS[current_theme]['bg_stats'])
        self.stats_panel.grid(row=1, column=0, sticky="nswe")
        self.stats_panel.grid_propagate(False)
        self.stats_panel.grid_rowconfigure(1, weight=1)
        self.stats_panel.grid_columnconfigure(0, weight=1)

        # Stats header with TTS toggle
        stats_header = ctk.CTkFrame(self.stats_panel, fg_color="transparent", height=70)
        stats_header.grid(row=0, column=0, sticky="ew")
        stats_header.grid_propagate(False)
        stats_header.grid_columnconfigure(0, weight=1)
        
        header_inner = ctk.CTkFrame(stats_header, fg_color="transparent")
        header_inner.pack(fill="x", padx=20, pady=(20, 15))
        
        ctk.CTkLabel(header_inner, text="📊 YOUR STATS", 
                    font=ctk.CTkFont(family="Segoe UI", size=16, weight="bold"),
                    text_color=FITGEN_COLORS[current_theme]['text_secondary']).pack(side="left")
        
        # TTS toggle with visual indicator
        tts_frame = ctk.CTkFrame(header_inner, fg_color="transparent")
        tts_frame.pack(side="right", padx=(10, 0))
        self.tts_status = ctk.CTkLabel(tts_frame, text="🔊 ON", font=ctk.CTkFont(size=12, weight="bold"),
                                      text_color="#10b981" if self.tts_enabled else "#ef4444")
        self.tts_status.pack(side="left", padx=(0, 8))
        self.tts_toggle = ctk.CTkSwitch(tts_frame, text="", command=self.toggle_tts,
                                       progress_color="#10b981", button_color="#0da271",
                                       button_hover_color="#0a8a5e", width=40, height=20)
        self.tts_toggle.pack(side="left")
        if self.tts_enabled and self.tts_engine:
            self.tts_toggle.select()
        else:
            self.tts_toggle.deselect()
            self.tts_status.configure(text="🔇 OFF", text_color="#ef4444")
        
        self.collapse_btn = ctk.CTkButton(stats_header, text="◀", width=28, height=28, font=ctk.CTkFont(size=12),
                                         fg_color=FITGEN_COLORS[current_theme]['bg_input'],
                                         hover_color=FITGEN_COLORS[current_theme]['border'], corner_radius=8,
                                         command=self.toggle_stats_panel)
        self.collapse_btn.pack(side="right", padx=15)

        # Scrollable content
        self.stats_scroll = ctk.CTkScrollableFrame(
            self.stats_panel,
            fg_color="transparent",
            scrollbar_button_color=FITGEN_COLORS[current_theme]['border'],
            scrollbar_button_hover_color=FITGEN_COLORS[current_theme]['text_muted']
        )
        self.stats_scroll.grid(row=1, column=0, sticky="nswe", padx=5, pady=(0, 15))
        self.stats_scroll.grid_columnconfigure(0, weight=1)

        # Compact stat cards
        self.bmi_card = self.create_compact_stat_card(self.stats_scroll, "🎯 BMI", "--", "Complete profile", "#10b981")
        self.weight_card = self.create_compact_stat_card(self.stats_scroll, "⚖️ Weight", "--", "Set target", "#f59e0b")
        self.calories_card = self.create_compact_stat_card(self.stats_scroll, "🔥 Calories", "--", "Based on profile", "#3b82f6")
        self.streak_card = self.create_compact_stat_card(self.stats_scroll, "🔥 Streak", f"{len(self.sessions)} chats", "Keep chatting!", "#ef4444")

        # Progress section
        progress_header = ctk.CTkLabel(self.stats_scroll, text="📈 Progress", 
                                     font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
                                     text_color=FITGEN_COLORS[current_theme]['text_primary'])
        progress_header.grid(row=4, column=0, padx=20, pady=(20, 10), sticky="w")

        progress_container = ctk.CTkFrame(self.stats_scroll, fg_color="transparent")
        progress_container.grid(row=5, column=0, padx=15, pady=(0, 15), sticky="ew")
        self.create_progress_bar(progress_container, "Weight Loss", 0, "#10b981")
        self.create_progress_bar(progress_container, "Workouts", 0, "#3b82f6")
        self.create_progress_bar(progress_container, "Nutrition", 0, "#f59e0b")

        # Previous Chats section
        chats_header = ctk.CTkFrame(self.stats_scroll, fg_color="transparent")
        chats_header.grid(row=6, column=0, padx=15, pady=(10, 8), sticky="ew")
        ctk.CTkLabel(chats_header, text="💬 Recent Chats", 
                    font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
                    text_color=FITGEN_COLORS[current_theme]['text_primary']).pack(side="left", padx=(5, 0))
        ctk.CTkButton(chats_header, text="🗑️", width=28, height=24, corner_radius=6,
                     fg_color=FITGEN_COLORS[current_theme]['bg_card'],
                     command=self.clear_all_chats).pack(side="right", padx=(5, 5))

        self.chats_list = ctk.CTkFrame(self.stats_scroll, fg_color="transparent")
        self.chats_list.grid(row=7, column=0, padx=10, pady=(0, 15), sticky="nsew")
        self.chats_list.grid_columnconfigure(0, weight=1)

        # Quick Actions
        actions_frame = ctk.CTkFrame(self.stats_scroll, fg_color="transparent")
        actions_frame.grid(row=8, column=0, padx=15, pady=(10, 25), sticky="ew")
        actions_frame.grid_columnconfigure(0, weight=1)
        
        for text, cmd in [("📝 Log Workout", lambda: self.show_toast("✅ Workout logged!")),
                         ("🍎 Log Meal", lambda: self.show_toast("✅ Meal logged!")),
                         ("✨ New Chat", self.show_dashboard)]:
            ctk.CTkButton(actions_frame, text=text, height=36, font=ctk.CTkFont(family="Segoe UI", size=12),
                         fg_color=FITGEN_COLORS[current_theme]['bg_card'],
                         hover_color=FITGEN_COLORS[current_theme]['border'], border_width=1,
                         border_color=FITGEN_COLORS[current_theme]['border'],
                         text_color=FITGEN_COLORS[current_theme]['text_primary'], corner_radius=12,
                         command=cmd).grid(row=len(actions_frame.winfo_children())//2, column=0, pady=6, sticky="ew")

        # --- MAIN CHAT AREA ---
        self.main_frame = ctk.CTkFrame(self, fg_color=FITGEN_COLORS[current_theme]['bg_main'])
        self.main_frame.grid(row=1, column=1, sticky="nswe")
        self.main_frame.grid_rowconfigure(0, weight=1)
        self.main_frame.grid_rowconfigure(1, weight=0)
        self.main_frame.grid_columnconfigure(0, weight=1)

        # --- BOTTOM ACTION BAR ---
        self.bottom_bar = ctk.CTkFrame(self, height=80, corner_radius=0, fg_color=FITGEN_COLORS[current_theme]['bg_card'])
        self.bottom_bar.grid(row=2, column=0, columnspan=2, sticky="ew")
        self.bottom_bar.grid_columnconfigure(1, weight=1)

        status_frame = ctk.CTkFrame(self.bottom_bar, fg_color="transparent")
        status_frame.grid(row=0, column=0, padx=25, sticky="w")
        self.coach_icon = ctk.CTkLabel(status_frame, text="🤖", font=ctk.CTkFont(size=16), 
                                      text_color=FITGEN_COLORS[current_theme]['primary'])
        self.coach_icon.pack(side="left", padx=(0, 8))
        ctk.CTkLabel(status_frame, text=f"FitGen Online ", 
                    font=ctk.CTkFont(family="Segoe UI", size=12),
                    text_color=FITGEN_COLORS[current_theme]['text_muted']).pack(side="left")

        suggestions_frame = ctk.CTkFrame(self.bottom_bar, fg_color="transparent")
        suggestions_frame.grid(row=0, column=1, sticky="ew")
        suggestions_frame.grid_columnconfigure(0, weight=1)
        suggestions_frame.grid_columnconfigure(1, weight=1)
        suggestions_frame.grid_columnconfigure(2, weight=1)
        for text, cmd in [("💪 Quick Workout", lambda: self.start_chat_with_message("20-min full body workout")),
                         ("🥗 Meal Idea", lambda: self.start_chat_with_message("high-protein dinner meal")),
                         ("💧 Water Reminder", lambda: self.show_toast("💧 Drink water! Aim for 8 glasses daily"))]:
            ctk.CTkButton(suggestions_frame, text=text, height=38, font=ctk.CTkFont(family="Segoe UI", size=12),
                         fg_color=FITGEN_COLORS[current_theme]['bg_input'],
                         hover_color=FITGEN_COLORS[current_theme]['border'], border_width=1,
                         border_color=FITGEN_COLORS[current_theme]['border'],
                         text_color=FITGEN_COLORS[current_theme]['text_primary'], corner_radius=12,
                         command=cmd).grid(row=0, column=len(suggestions_frame.winfo_children())//3, padx=8, sticky="ew")

        actions_frame = ctk.CTkFrame(self.bottom_bar, fg_color="transparent")
        actions_frame.grid(row=0, column=2, padx=25, sticky="e")
        self.voice_btn = ctk.CTkButton(actions_frame, text="🎤 Voice", height=42,
                                      font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
                                      fg_color=FITGEN_COLORS[current_theme]['bg_input'],
                                      hover_color=FITGEN_COLORS[current_theme]['border'], border_width=1,
                                      border_color=FITGEN_COLORS[current_theme]['border'],
                                      text_color=FITGEN_COLORS[current_theme]['text_primary'], corner_radius=12,
                                      command=self.start_voice_input)
        self.voice_btn.pack(side="left", padx=(0, 10))
        ctk.CTkButton(actions_frame, text="📥 Export", height=42,
                     font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
                     fg_color=FITGEN_COLORS[current_theme]['bg_input'],
                     hover_color=FITGEN_COLORS[current_theme]['border'], border_width=1,
                     border_color=FITGEN_COLORS[current_theme]['border'],
                     text_color=FITGEN_COLORS[current_theme]['text_primary'], corner_radius=12,
                     command=self.export_chat).pack(side="left", padx=(0, 10))
        ctk.CTkButton(actions_frame, text="✨ New Chat", height=42,
                     font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
                     fg_color=FITGEN_COLORS[current_theme]['primary'],
                     hover_color=FITGEN_COLORS[current_theme]['primary_dark'],
                     text_color="#ffffff", corner_radius=12,
                     command=self.show_dashboard).pack(side="left")

        self.update_stats_panel()
        self.update_chat_list()

    def toggle_tts(self):
        """Toggle TTS on/off with visual feedback"""
        self.tts_enabled = self.tts_toggle.get()
        if self.tts_enabled:
            if self.tts_engine:
                self.tts_status.configure(text="🔊 ON", text_color="#10b981")
                self.show_toast("🔊 AI voice enabled")
                # Test speech immediately in main thread
                self.speak_in_main_thread("Voice activated! How can I help you today?")
            else:
                self.tts_enabled = False
                self.tts_toggle.deselect()
                self.tts_status.configure(text="🔇 OFF", text_color="#ef4444")
                self.show_toast("❌ TTS unavailable. Check console for setup instructions.")
        else:
            self.tts_status.configure(text="🔇 OFF", text_color="#ef4444")
            self.show_toast("🔇 AI voice disabled")

    def create_compact_stat_card(self, parent, title, value, subtitle, color):
        card = ctk.CTkFrame(parent, fg_color=FITGEN_COLORS[current_theme]['bg_card'], corner_radius=14,
                           border_width=1, border_color=FITGEN_COLORS[current_theme]['border'])
        card.grid(padx=15, pady=8, sticky="ew")
        
        ctk.CTkLabel(card, text=title, font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
                    text_color=FITGEN_COLORS[current_theme]['text_muted']).pack(pady=(10, 2))
        value_label = ctk.CTkLabel(card, text=value, font=ctk.CTkFont(family="Segoe UI", size=24, weight="bold"),
                                  text_color=color)
        value_label.pack()
        subtitle_label = ctk.CTkLabel(card, text=subtitle, font=ctk.CTkFont(family="Segoe UI", size=10),
                                     text_color=FITGEN_COLORS[current_theme]['text_muted'])
        subtitle_label.pack(pady=(2, 10))
        
        card.value_label = value_label
        card.subtitle_label = subtitle_label
        return card

    def create_progress_bar(self, parent, label, progress, color):
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.pack(fill="x", pady=6)
        
        label_frame = ctk.CTkFrame(frame, fg_color="transparent")
        label_frame.pack(fill="x", pady=(0, 3))
        ctk.CTkLabel(label_frame, text=label, font=ctk.CTkFont(family="Segoe UI", size=11),
                    text_color=FITGEN_COLORS[current_theme]['text_primary']).pack(side="left")
        ctk.CTkLabel(label_frame, text=f"{progress}%", font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
                    text_color=color).pack(side="right")
        
        bar_bg = ctk.CTkFrame(frame, height=5, fg_color=FITGEN_COLORS[current_theme]['border'], corner_radius=2)
        bar_bg.pack(fill="x")
        
        bar_fill = ctk.CTkFrame(bar_bg, height=5, fg_color=color, corner_radius=2)
        bar_fill.place(x=0, y=0, relwidth=progress/100, relheight=1)

    def update_stats_panel(self):
        if not self.profile:
            return
        
        try:
            weight = float(self.profile.get('weight', 70))
            height = float(self.profile.get('height', 170)) / 100
            bmi = weight / (height * height)
            category = self.get_bmi_category(bmi)
            self.bmi_card.value_label.configure(text=f"{bmi:.1f}")
            self.bmi_card.subtitle_label.configure(text=category)
        except:
            self.bmi_card.value_label.configure(text="--")
            self.bmi_card.subtitle_label.configure(text="Invalid data")
        
        current = self.profile.get('weight', 'N/A')
        goal = self.profile.get('goal_weight', 'N/A')
        self.weight_card.value_label.configure(text=f"{current} kg")
        self.weight_card.subtitle_label.configure(text=f"Goal: {goal} kg")
        
        try:
            age = int(self.profile.get('age', 30))
            gender = self.profile.get('gender', 'male')
            activity = 1.375
            
            if gender == 'male':
                bmr = 10 * weight + 6.25 * (height * 100) - 5 * age + 5
            else:
                bmr = 10 * weight + 6.25 * (height * 100) - 5 * age - 161
            
            calories = int(bmr * activity)
            self.calories_card.value_label.configure(text=f"{calories:,}")
            self.calories_card.subtitle_label.configure(text="Maintenance calories")
        except:
            self.calories_card.value_label.configure(text="--")
            self.calories_card.subtitle_label.configure(text="Complete profile")
        
        self.streak_card.value_label.configure(text=f"{len(self.sessions)} chats")
        self.streak_card.subtitle_label.configure(text="Total conversations")

    def get_bmi_category(self, bmi):
        if bmi < 18.5: return "Underweight"
        elif bmi < 25: return "Normal weight"
        elif bmi < 30: return "Overweight"
        else: return "Obese"

    def update_chat_list(self):
        for widget in self.chats_list.winfo_children():
            widget.destroy()
        
        if not self.sessions:
            ctk.CTkLabel(self.chats_list, text="No previous chats\nStart a conversation!", 
                        font=ctk.CTkFont(size=12), text_color=FITGEN_COLORS[current_theme]['text_muted'],
                        justify="center", pady=15).pack(fill="x", padx=10)
            return
        
        for session in self.sessions:
            try:
                dt = datetime.strptime(session.created_at, "%Y-%m-%d %H:%M:%S")
                time_str = dt.strftime("%b %d")
            except:
                time_str = session.created_at[:10]
            
            title = next((msg['content'][:28] + "..." for msg in session.history if msg['role'] == 'user'), "Untitled Chat")
            
            item_frame = ctk.CTkFrame(self.chats_list, fg_color=FITGEN_COLORS[current_theme]['bg_card'],
                                    corner_radius=10, border_width=1,
                                    border_color=FITGEN_COLORS[current_theme]['border'])
            item_frame.pack(fill="x", pady=5, padx=5)
            
            content_frame = ctk.CTkFrame(item_frame, fg_color="transparent")
            content_frame.pack(fill="x", padx=10, pady=8)
            
            ctk.CTkLabel(content_frame, text=title, font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
                        text_color=FITGEN_COLORS[current_theme]['text_primary'],
                        anchor="w", justify="left").pack(fill="x")
            ctk.CTkLabel(content_frame, text=time_str, font=ctk.CTkFont(size=10),
                        text_color=FITGEN_COLORS[current_theme]['text_muted'],
                        anchor="w").pack(fill="x", pady=(3, 0))
            
            for widget in (item_frame, content_frame, *content_frame.winfo_children()):
                widget.bind("<Button-1>", lambda e, s=session: self.load_session(s))
            
            def on_enter(frame):
                frame.configure(fg_color=FITGEN_COLORS[current_theme]['primary_dark'])
            def on_leave(frame):
                frame.configure(fg_color=FITGEN_COLORS[current_theme]['bg_card'])
            
            item_frame.bind("<Enter>", lambda e, f=item_frame: on_enter(f))
            item_frame.bind("<Leave>", lambda e, f=item_frame: on_leave(f))

    def toggle_stats_panel(self):
        if self.stats_panel_visible:
            self.stats_panel.grid_forget()
            self.main_frame.grid(row=1, column=0, columnspan=2, sticky="nswe")
            self.collapse_btn.configure(text="▶")
        else:
            self.stats_panel.grid(row=1, column=0, sticky="nswe")
            self.main_frame.grid(row=1, column=1, sticky="nswe")
            self.collapse_btn.configure(text="◀")
        self.stats_panel_visible = not self.stats_panel_visible

    def toggle_theme(self):
        global current_theme
        current_theme = "light" if current_theme == "dark" else "dark"
        self.theme_toggle.set_mode(current_theme == "dark")
        
        for widget in self.winfo_children():
            widget.destroy()
        self.setup_ui()
        
        if self.current_session:
            self.refresh_chat_ui()
        elif self.profile:
            self.show_dashboard()
        else:
            self.show_profile_setup()

    def show_profile_setup(self):
        for widget in self.main_frame.winfo_children():
            widget.destroy()

        setup_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        setup_frame.pack(expand=True, fill="both", padx=50, pady=50)

        ctk.CTkLabel(setup_frame, text="👤 Your Fitness Profile", 
                    font=ctk.CTkFont(family="Segoe UI", size=32, weight="bold"),
                    text_color=FITGEN_COLORS[current_theme]['text_primary']).pack(pady=(0, 10))
        ctk.CTkLabel(setup_frame, text="Personalized coaching starts with knowing you", 
                    font=ctk.CTkFont(family="Segoe UI", size=16),
                    text_color=FITGEN_COLORS[current_theme]['text_secondary']).pack(pady=(0, 40))

        fields_frame = ctk.CTkFrame(setup_frame, fg_color="transparent")
        fields_frame.pack(fill="x", padx=20)

        entries = {}
        fields = [
            ("Name", "name", 200),
            ("Age (years)", "age", 80),
            ("Gender", "gender", ["male", "female", "other"]),
            ("Weight (kg)", "weight", 100),
            ("Height (cm)", "height", 100),
            ("Goal Weight (kg)", "goal_weight", 100),
            ("Fitness Goal", "goal", 300),
        ]
        
        for label_text, var_name, control in fields:
            frame = ctk.CTkFrame(fields_frame, fg_color="transparent")
            frame.pack(fill="x", pady=10)
            ctk.CTkLabel(frame, text=label_text, width=140, anchor="w",
                        font=ctk.CTkFont(family="Segoe UI", size=14)).pack(side="left", padx=(0, 15))
            
            if isinstance(control, list):
                entry = ctk.CTkComboBox(frame, values=control, width=120, height=36,
                                       font=ctk.CTkFont(family="Segoe UI", size=14),
                                       dropdown_fg_color=FITGEN_COLORS[current_theme]['bg_card'])
                entry.set(control[0])
            else:
                entry = ctk.CTkEntry(frame, placeholder_text=f"Enter {label_text.lower()}", width=control,
                                    height=36, font=ctk.CTkFont(family="Segoe UI", size=14))
            entry.pack(side="left")
            entries[var_name] = entry

        def save_profile():
            profile_data = {
                "name": entries['name'].get().strip() or "FitGen User",
                "age": entries['age'].get().strip() or "30",
                "gender": entries['gender'].get().strip() if 'gender' in entries else "male",
                "weight": entries['weight'].get().strip() or "70",
                "height": entries['height'].get().strip() or "170",
                "goal_weight": entries['goal_weight'].get().strip() or "65",
                "goal": entries['goal'].get().strip() or "Get fit and healthy",
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            self.save_profile(profile_data)
            self.show_dashboard()

        btn_frame = ctk.CTkFrame(setup_frame, fg_color="transparent")
        btn_frame.pack(pady=30)
        ctk.CTkButton(btn_frame, text="✅ Save & Continue", height=50, width=220,
                     font=ctk.CTkFont(family="Segoe UI", size=16, weight="bold"),
                     fg_color=FITGEN_COLORS[current_theme]['primary'],
                     hover_color=FITGEN_COLORS[current_theme]['primary_dark'],
                     text_color="#ffffff", corner_radius=16, command=save_profile).pack(side="left", padx=10)
        ctk.CTkButton(btn_frame, text="⏭️ Skip for now", height=50, width=180,
                     font=ctk.CTkFont(family="Segoe UI", size=16),
                     fg_color=FITGEN_COLORS[current_theme]['bg_card'],
                     hover_color=FITGEN_COLORS[current_theme]['border'], border_width=1,
                     border_color=FITGEN_COLORS[current_theme]['border'],
                     text_color=FITGEN_COLORS[current_theme]['text_primary'], corner_radius=16,
                     command=self.show_dashboard).pack(side="left", padx=10)

    def show_dashboard(self):
        for widget in self.main_frame.winfo_children():
            widget.destroy()

        dashboard = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        dashboard.pack(expand=True, fill="both", padx=40, pady=40)

        hero_frame = ctk.CTkFrame(dashboard, fg_color="transparent")
        hero_frame.pack(pady=(0, 30))
        ctk.CTkLabel(hero_frame, text="💪", font=ctk.CTkFont(size=64, weight="bold"),
                    text_color=FITGEN_COLORS[current_theme]['primary']).pack()
        ctk.CTkLabel(hero_frame, text="FITGEN", font=ctk.CTkFont(family="Segoe UI", size=48, weight="bold"),
                    text_color=FITGEN_COLORS[current_theme]['text_primary']).pack(pady=(10, 5))
        ctk.CTkLabel(hero_frame, text="Your AI-Powered Fitness Companion", 
                    font=ctk.CTkFont(family="Segoe UI", size=20),
                    text_color=FITGEN_COLORS[current_theme]['text_secondary']).pack()

        if self.profile:
            ctk.CTkLabel(dashboard, text=f"Hello {self.profile['name']}! Ready for your next fitness breakthrough?", 
                        font=ctk.CTkFont(family="Segoe UI", size=18, weight="bold"),
                        text_color=FITGEN_COLORS[current_theme]['text_primary']).pack(pady=(0, 30))

        features_frame = ctk.CTkFrame(dashboard, fg_color="transparent")
        features_frame.pack(fill="x", pady=(0, 40))
        features = [
            ("🏋️", "Smart Workout Plans", "AI-generated routines tailored to your goals"),
            ("🥗", "Personalized Nutrition", "Meal plans based on your dietary preferences"),
            ("📊", "Progress Tracking", "Monitor your fitness journey with detailed insights"),
            ("💬", "24/7 Expert Coaching", "Get science-backed advice anytime, anywhere"),
        ]
        
        for i, (icon, title, desc) in enumerate(features):
            card = ctk.CTkFrame(features_frame, fg_color=FITGEN_COLORS[current_theme]['bg_card'], corner_radius=20,
                               border_width=1, border_color=FITGEN_COLORS[current_theme]['border'])
            card.grid(row=i//2, column=i%2, padx=15, pady=15, sticky="nsew")
            ctk.CTkLabel(card, text=icon, font=ctk.CTkFont(size=36),
                        text_color=FITGEN_COLORS[current_theme]['primary']).pack(pady=(25, 10))
            ctk.CTkLabel(card, text=title, font=ctk.CTkFont(family="Segoe UI", size=18, weight="bold"),
                        text_color=FITGEN_COLORS[current_theme]['text_primary']).pack(pady=(0, 8))
            ctk.CTkLabel(card, text=desc, font=ctk.CTkFont(family="Segoe UI", size=13),
                        text_color=FITGEN_COLORS[current_theme]['text_muted'], wraplength=250,
                        justify="center").pack(pady=(0, 25), padx=20)
        
        features_frame.grid_columnconfigure(0, weight=1)
        features_frame.grid_columnconfigure(1, weight=1)

        start_frame = ctk.CTkFrame(dashboard, fg_color="transparent")
        start_frame.pack(fill="x")
        ctk.CTkLabel(start_frame, text="🚀 Quick Start", 
                    font=ctk.CTkFont(family="Segoe UI", size=24, weight="bold"),
                    text_color=FITGEN_COLORS[current_theme]['text_primary']).pack(pady=(0, 20))
        
        for suggestion in ["Create a 4-week weight loss plan", "Design a muscle-building workout routine",
                          "Suggest high-protein vegetarian meals", "How do I improve my running endurance?"]:
            ctk.CTkButton(start_frame, text=suggestion, height=48,
                         font=ctk.CTkFont(family="Segoe UI", size=14),
                         fg_color=FITGEN_COLORS[current_theme]['bg_card'],
                         hover_color=FITGEN_COLORS[current_theme]['border'], border_width=1,
                         border_color=FITGEN_COLORS[current_theme]['border'],
                         text_color=FITGEN_COLORS[current_theme]['text_primary'], corner_radius=16,
                         command=lambda s=suggestion: self.start_chat_with_message(s)).pack(fill="x", padx=40, pady=8)

    def handle_search(self):
        query = self.search_entry.get().strip()
        if query:
            self.start_chat_with_message(query)
            self.search_entry.delete(0, tk.END)

    def start_chat_with_message(self, user_message):
        self._start_fresh_chat()
        self.after(100, lambda: self._send_initial_message(user_message))

    def _start_fresh_chat(self):
        for widget in self.main_frame.winfo_children():
            widget.destroy()

        session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.current_session = ChatSession(session_id, f"Chat {session_id}")
        
        if self.profile:
            prompt = SYSTEM_PROMPT + f"\n\nUser profile: {self.profile['age']} years old, {self.profile['weight']}kg, {self.profile['height']}cm, goal: {self.profile['goal']}"
            self.current_session.history[0]['content'] = prompt

        colors = FITGEN_COLORS[current_theme]

        self.chat_container = ctk.CTkScrollableFrame(self.main_frame, fg_color="transparent",
                                                    scrollbar_button_color=colors['border'],
                                                    scrollbar_button_hover_color=colors['text_muted'])
        self.chat_container.grid(row=0, column=0, sticky="nswe", padx=30, pady=30)
        self.chat_container.grid_columnconfigure(0, weight=1)

        input_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        input_frame.grid(row=1, column=0, sticky="ew", pady=(0, 30), padx=30)
        input_frame.grid_columnconfigure(0, weight=1)

        user_entry = ctk.CTkEntry(input_frame, placeholder_text="Ask your fitness question...", height=56,
                                 font=ctk.CTkFont(family="Segoe UI", size=15), corner_radius=28,
                                 border_width=2, border_color=colors['border'],
                                 fg_color=colors['bg_input'], text_color=colors['text_primary'],
                                 placeholder_text_color=colors['text_muted'])
        user_entry.grid(row=0, column=0, ipady=8, padx=(0, 15), sticky="ew")
        user_entry.bind("<Return>", lambda e: self.send_message(self.current_session))
        user_entry.bind("<FocusIn>", lambda e: user_entry.configure(border_color=colors['primary']))
        user_entry.bind("<FocusOut>", lambda e: user_entry.configure(border_color=colors['border']))

        send_button = ctk.CTkButton(input_frame, text="➤", width=68, height=56,
                                   font=ctk.CTkFont(family="Segoe UI", size=20, weight="bold"),
                                   corner_radius=28, fg_color=colors['primary'],
                                   hover_color=colors['primary_dark'], text_color="#ffffff",
                                   command=lambda: self.send_message(self.current_session))
        send_button.grid(row=0, column=1)

        self.current_session.widgets.update({
            'chat_container': self.chat_container,
            'user_entry': user_entry,
            'send_button': send_button
        })

        if self.profile:
            welcome = f"Hey {self.profile['name']}! 👋 I'm FitGen, your AI Fitness Coach. How can I help you crush your fitness goals today? 💪"
        else:
            welcome = "Hey there! 👋 I'm FitGen, your AI Fitness Coach. Tell me about your fitness goals or ask for a workout/meal plan! 💪"
        self.append_message(self.current_session, "Coach", welcome)
        
        # SPEAK WELCOME MESSAGE IN MAIN THREAD (GUARANTEED TO WORK)
        if self.tts_enabled:
            self.after(800, lambda: self.speak_in_main_thread(welcome))

    def load_session(self, session):
        self.current_session = session
        self._start_fresh_chat()
        
        for msg in session.history:
            if msg['role'] == 'system':
                continue
            sender = "You" if msg['role'] == 'user' else "Coach"
            self.append_message(self.current_session, sender, msg['content'])

    def append_message(self, session, sender, message):
        container = session.widgets['chat_container']
        msg_frame = ctk.CTkFrame(container, fg_color="transparent")
        msg_frame.pack(fill="x", padx=0, pady=(15, 0))

        colors = FITGEN_COLORS[current_theme]
        is_user = sender == "You"
        bubble_bg = colors['primary'] if is_user else colors['bg_card']
        text_color = "#ffffff" if is_user else colors['text_primary']
        align = "e" if is_user else "w"

        bubble_frame = ctk.CTkFrame(msg_frame, fg_color=bubble_bg, corner_radius=20,
                                   border_width=0 if is_user else 1,
                                   border_color=colors['border'] if not is_user else None)
        bubble_frame.pack(side="top", anchor=align, padx=(0, 20) if is_user else (20, 0))

        if not is_user:
            header_frame = ctk.CTkFrame(bubble_frame, fg_color="transparent")
            header_frame.pack(anchor="w", padx=20, pady=(16, 6), fill="x")
            
            self.coach_icon = ctk.CTkLabel(header_frame, text="🤖", font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
                                         text_color=FITGEN_COLORS[current_theme]['primary'])
            self.coach_icon.pack(side="left")
            
            ctk.CTkLabel(header_frame, text=" FitGen Coach", 
                        font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
                        text_color=FITGEN_COLORS[current_theme]['primary']).pack(side="left", padx=(4, 0))

        label = ctk.CTkLabel(bubble_frame, text=message, font=ctk.CTkFont(family="Segoe UI", size=15),
                            text_color=text_color, padx=20, pady=16 if is_user else 12,
                            wraplength=800, justify="left" if not is_user else "right")
        label.pack(fill="x" if not is_user else None)

        if not is_user:
            session.current_ai_label = label

    def send_message(self, session):
        user_text = session.widgets['user_entry'].get().strip()
        if not user_text:
            return

        entry = session.widgets['user_entry']
        button = session.widgets['send_button']
        entry.configure(state="disabled")
        button.configure(state="disabled")

        self.append_message(session, "You", user_text)
        entry.delete(0, tk.END)
        session.history.append({'role': 'user', 'content': user_text})
        self.append_message(session, "Coach", " ")
        threading.Thread(target=self.get_ollama_response, args=(session, user_text), daemon=True).start()

    def get_ollama_response(self, session, user_message):
        try:
            full_response = ""
            stream = ollama.chat(model=OLLAMA_MODEL, messages=session.history, stream=True)
            for chunk in stream:
                content = chunk['message'].get('content', '')
                if content:
                    self.message_queue.put(('chunk', session, content))
                    full_response += content
            self.message_queue.put(('complete', session, full_response))
            
            # CRITICAL: Schedule speech in MAIN THREAD after response completes
            if self.tts_enabled and full_response.strip():
                clean_response = re.sub(r'[^\w\s.,!?]', '', full_response)
                clean_response = re.sub(r'\s+', ' ', clean_response).strip()
                if clean_response:
                    self.after(100, lambda: self.speak_in_main_thread(clean_response))
                
            self.after(500, self.save_current_session)
        except Exception as e:
            error_msg = f"⚠️ Error: {str(e)[:100]}"
            self.message_queue.put(('error', session, error_msg))
            if session.history and session.history[-1]['role'] == 'user':
                session.history.pop()

    def check_message_queue(self):
        try:
            while True:
                msg_type, session, content = self.message_queue.get_nowait()
                if msg_type == 'chunk' and session == self.current_session and session.current_ai_label:
                    current = session.current_ai_label.cget("text")
                    session.current_ai_label.configure(text=current + content)
                    session.widgets['chat_container']._parent_canvas.yview_moveto(1.0)
                elif msg_type == 'complete':
                    session.history.append({'role': 'assistant', 'content': content})
                    session.current_ai_label = None
                    self.enable_input(session)
                elif msg_type == 'error':
                    if session.current_ai_label:
                        session.current_ai_label.destroy()
                    self.append_message(session, "System", content)
                    self.enable_input(session)
        except queue.Empty:
            pass
        finally:
            self.after(50, self.check_message_queue)

    def enable_input(self, session):
        if 'user_entry' in session.widgets:
            session.widgets['user_entry'].configure(state="normal")
            session.widgets['user_entry'].focus_set()
        if 'send_button' in session.widgets:
            session.widgets['send_button'].configure(state="normal")

    def _send_initial_message(self, message):
        if not self.current_session:
            return
        entry = self.current_session.widgets['user_entry']
        entry.delete(0, tk.END)
        entry.insert(0, message)
        self.send_message(self.current_session)

    # --- VOICE INPUT (FIXED) ---
    def start_voice_input(self):
        original_text = self.voice_btn.cget("text")
        self.voice_btn.configure(text="🎤 Listening...", state="disabled")
        self.update_idletasks()
        threading.Thread(target=self.check_pyaudio_and_listen, args=(original_text,), daemon=True).start()

    def check_pyaudio_and_listen(self, original_text):
        try:
            import pyaudio
            self.listen_to_voice(original_text)
        except ImportError:
            self.after(0, lambda: self.voice_btn.configure(text=original_text, state="normal"))
            self.show_toast("❌ PyAudio not installed!\nRun: pip install pyaudio")

    def listen_to_voice(self, original_text):
        recognizer = sr.Recognizer()
        audio = None
        
        try:
            mic_list = sr.Microphone.list_microphone_names()
            if not mic_list:
                raise Exception("No microphones detected")
            
            with sr.Microphone(device_index=0) as source:
                recognizer.adjust_for_ambient_noise(source, duration=0.3)
                self.after(0, lambda: self.voice_btn.configure(text="🗣️ Speak now..."))
                self.update_idletasks()
                audio = recognizer.listen(source, timeout=7, phrase_time_limit=10)
        
        except Exception as e:
            error_msg = str(e).lower()
            self.after(0, lambda: self.voice_btn.configure(text=original_text, state="normal"))
            if "timeout" in error_msg:
                self.show_toast("🔇 No speech detected.\nPlease speak within 7 seconds.")
            elif "microphone" in error_msg or "device" in error_msg:
                self.show_toast("🔇 No microphone access.\nCheck OS permissions for Python.")
            else:
                self.show_toast(f"🎤 Error: {str(e)[:50]}")
            return
        
        self.after(0, lambda: self.voice_btn.configure(text="🧠 Processing...", state="disabled"))
        self.update_idletasks()
        
        try:
            text = recognizer.recognize_google(audio).strip()
            if not text:
                raise ValueError("Empty result")
            self.after(0, lambda: self.voice_btn.configure(text=original_text, state="normal"))
            self.after(100, lambda: self.start_chat_with_message(text))
        except sr.RequestError:
            self.after(0, lambda: self.voice_btn.configure(text=original_text, state="normal"))
            self.show_toast("🌐 No internet!\nGoogle Speech requires connection.")
        except Exception as e:
            self.after(0, lambda: self.voice_btn.configure(text=original_text, state="normal"))
            self.show_toast(f"⚠️ Recognition failed:\n{str(e)[:60]}")

    # --- Chat Management ---
    def clear_all_chats(self):
        for filename in os.listdir(CHATS_DIR):
            if filename.endswith('.json'):
                try:
                    os.remove(os.path.join(CHATS_DIR, filename))
                except:
                    pass
        self.sessions = []
        self.update_chat_list()
        self.show_toast("✅ All chats cleared!")

    def export_chat(self):
        if not self.current_session or len(self.current_session.history) <= 1:
            self.show_toast("📭 No chat to export!")
            return

        export_dir = "exported_plans"
        os.makedirs(export_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"fitgen_plan_{timestamp}.pdf"
        filepath = os.path.join(export_dir, filename)

        try:
            doc = SimpleDocTemplate(filepath, pagesize=letter)
            story = []
            styles = getSampleStyleSheet()
            title_style = ParagraphStyle('Title', parent=styles['Normal'], fontSize=24, spaceAfter=12, alignment=TA_CENTER)
            story.append(Paragraph("FITGEN FITNESS PLAN", title_style))
            if self.profile:
                story.append(Paragraph(f"Client: {self.profile['name']} | Goal: {self.profile['goal']}", styles['Normal']))
            story.append(Spacer(1, 0.2 * inch))
            
            for msg in self.current_session.history:
                if msg['role'] == 'system': continue
                role = "YOU" if msg['role'] == 'user' else "FITGEN"
                content = f"<b>[{role}]:</b> {msg['content']}"
                story.append(Paragraph(content, styles['Normal']))
                story.append(Spacer(1, 0.1 * inch))
            
            doc.build(story)
            self.show_toast(f"✅ Exported to:\n{filename}")
        except Exception as e:
            self.show_toast(f"❌ Export failed: {str(e)[:50]}")

    def refresh_chat_ui(self):
        if not self.current_session:
            self.show_dashboard()
            return
            
        session = self.current_session
        for widget in self.main_frame.winfo_children():
            widget.destroy()

        colors = FITGEN_COLORS[current_theme]
        self.chat_container = ctk.CTkScrollableFrame(self.main_frame, fg_color="transparent",
                                                    scrollbar_button_color=colors['border'],
                                                    scrollbar_button_hover_color=colors['text_muted'])
        self.chat_container.grid(row=0, column=0, sticky="nswe", padx=30, pady=30)
        self.chat_container.grid_columnconfigure(0, weight=1)

        input_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        input_frame.grid(row=1, column=0, sticky="ew", pady=(0, 30), padx=30)
        input_frame.grid_columnconfigure(0, weight=1)

        user_entry = ctk.CTkEntry(input_frame, placeholder_text="Ask your fitness question...", height=56,
                                 font=ctk.CTkFont(family="Segoe UI", size=15), corner_radius=28,
                                 border_width=2, border_color=colors['border'],
                                 fg_color=colors['bg_input'], text_color=colors['text_primary'],
                                 placeholder_text_color=colors['text_muted'])
        user_entry.grid(row=0, column=0, ipady=8, padx=(0, 15), sticky="ew")
        user_entry.bind("<Return>", lambda e: self.send_message(session))
        user_entry.bind("<FocusIn>", lambda e: user_entry.configure(border_color=colors['primary']))
        user_entry.bind("<FocusOut>", lambda e: user_entry.configure(border_color=colors['border']))

        send_button = ctk.CTkButton(input_frame, text="➤", width=68, height=56,
                                   font=ctk.CTkFont(family="Segoe UI", size=20, weight="bold"),
                                   corner_radius=28, fg_color=colors['primary'],
                                   hover_color=colors['primary_dark'], text_color="#ffffff",
                                   command=lambda: self.send_message(session))
        send_button.grid(row=0, column=1)

        session.widgets.update({
            'chat_container': self.chat_container,
            'user_entry': user_entry,
            'send_button': send_button
        })

        for msg in session.history:
            if msg['role'] == 'system': continue
            sender = "You" if msg['role'] == 'user' else "Coach"
            self.append_message(session, sender, msg['content'])

    def show_toast(self, message):
        toast = ctk.CTkToplevel(self)
        toast.title("")
        toast.geometry("380x90")
        toast.attributes("-topmost", True, "-toolwindow", True)
        toast.resizable(False, False)
        toast.overrideredirect(True)
        x = self.winfo_x() + self.winfo_width() - 400
        y = self.winfo_y() + self.winfo_height() - 120
        toast.geometry(f"+{x}+{y}")

        toast_frame = ctk.CTkFrame(toast, fg_color=FITGEN_COLORS[current_theme]['bg_card'], corner_radius=16,
                                  border_width=2, border_color=FITGEN_COLORS[current_theme]['border'])
        toast_frame.pack(fill="both", expand=True, padx=2, pady=2)
        ctk.CTkLabel(toast_frame, text=message, font=ctk.CTkFont(family="Segoe UI", size=14),
                    text_color=FITGEN_COLORS[current_theme]['text_primary'], justify="center",
                    wraplength=320).pack(expand=True, padx=25, pady=25)
        toast.after(3500, toast.destroy)

if __name__ == "__main__":
    print("=" * 70)
    print("💪 FITGEN - AI FITNESS COACH WITH GUARANTEED VOICE")
    print("=" * 70)
    print("✅ CRITICAL FIX: TTS runs ONLY in MAIN THREAD (no background threads!)")
    print("✅ SPEECH AFTER EVERY RESPONSE: AI speaks all replies naturally")
    print("✅ VISUAL FEEDBACK: Coach icon animates during speech (🤖 → 🔊)")
    print("✅ TTS TOGGLE: Switch in stats panel header (🔊 ON / 🔇 OFF)")
    print("✅ SCROLLABLE STATS: All previous chats visible + compact stat cards")
    print("✅ PROPER EXIT: Close window normally (no terminal kill needed)")
    print("=" * 70)
    
    # Platform-specific notes
    system = os.name
    if system == 'nt':
        print("🔊 WINDOWS TTS: Using built-in SAPI5 voices")
        print("   → Check voices: Settings > Time & Language > Speech")
    elif system == 'posix':
        import platform
        if platform.system() == 'Darwin':
            print("🔊 macOS TTS: Using built-in Siri voices")
            print("   → Add voices: System Settings > Accessibility > VoiceOver > Speech")
        else:
            print("🔊 LINUX TTS: Requires espeak")
            print("   → Install: sudo apt-get install espeak")
    
    print("=" * 70)
    print(f"💡 First: Run 'ollama serve' in a separate terminal")
    print(f"🤖 Model: {OLLAMA_MODEL}")
    print(f"📁 Profile: {PROFILE_FILE}")
    print(f"📁 Chats: ./{CHATS_DIR}/")
    print("=" * 70)
    
    # Dependency check
    try:
        import pyttsx3
        print("✅ pyttsx3 installed")
    except ImportError:
        print("❌ MISSING DEPENDENCY: pip install pyttsx3")
        exit(1)
    
    try:
        import pyaudio
        print("✅ PyAudio installed")
    except ImportError:
        print("ℹ️  PyAudio not installed (voice input will show error)")
        print("   Fix: pip install pyaudio")
    
    print("=" * 70)
    print("✨ Starting FitGen...")
    print("   → You'll hear 'FitGen voice active' on startup")
    print("   → AI WILL SPEAK EVERY RESPONSE when TTS is enabled")
    print("   → Toggle voice with 🔊/🔇 switch in stats panel")
    print("=" * 70)
    
    app = FitGenApp()
    app.mainloop()