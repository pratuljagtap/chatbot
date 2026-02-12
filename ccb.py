import os
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.units import inch
import customtkinter as ctk
import ollama
import threading
import queue
import tkinter as tk
import speech_recognition as sr
import pandas as pd
import glob
import json

# --- Configuration ---
OLLAMA_MODEL = "llama3"
WINDOW_WIDTH = 1000
WINDOW_HEIGHT = 700
SIDEBAR_WIDTH = 260
MAIN_AREA_PAD = 50

# System prompt to strictly constrain AI to fitness topics
SYSTEM_PROMPT = (
    "You are an expert AI Fitness Coach. Your ONLY purpose is to help users with workout plans, "
    "diet/nutrition advice, weight loss, muscle gain, supplementation, recovery, mobility, and goal setting. "
    "NEVER discuss politics, technology, coding, entertainment, or unrelated topics. "
    "If asked something off-topic, politely say: \"I'm your Fitness Coach — let's focus on your health goals! 💪\" "
    "Keep responses encouraging, science-based, and personalized. Use emojis sparingly to stay professional yet friendly. "
    "Always ask clarifying questions if the user's goal is unclear."
)

# Colors (Dark Theme)
DARK_COLORS = {
    'sidebar_bg': "#212121",
    'header_text': "#ffffff",
    'new_chat_bg': "#40a800",
    'new_chat_hover': "#00885b",
    'chat_item_bg': "#2d2d30",
    'chat_item_hover': "#3c3c40",
    'selected_bg': "#0084ff",
    'user_bubble': "#0084ff",
    'ai_bubble': "#383838",
    'text': "#ffffff",
    'main_bg': "#1f1f1f",
    'entry_bg': "#333333"
}

# Colors (Light Theme)
LIGHT_COLORS = {
    'sidebar_bg': "#f0f0f0",
    'header_text': "#333333",
    'new_chat_bg': "#4CAF50",
    'new_chat_hover': "#388E3C",
    'chat_item_bg': "#e0e0e0",
    'chat_item_hover': "#d0d0d0",
    'selected_bg': "#2196F3",
    'user_bubble': "#2196F3",
    'ai_bubble': "#f5f5f5",
    'text': "#333333",
    'main_bg': "#fafafa",
    'entry_bg': "#ffffff"
}

# Font
DEFAULT_FONT = ("Segoe UI", 14)
CHAT_DIR = "chat_logs"
os.makedirs(CHAT_DIR, exist_ok=True)

# Global state
current_theme = "dark"

class ChatSession:
    def __init__(self, name="Current Session"):
        self.name = name
        self.history = []
        self.widgets = {}
        self.current_ai_label = None

class ChatbotApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("🧠 Workout & Diet AI Coach")
        self.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
        self.resizable(True, True)

        self.current_session = None
        self.message_queue = queue.Queue()

        self.setup_ui()
        self.load_chat_buttons()
        self.show_welcome_screen()

        self.after(100, self.check_message_queue)

    def setup_ui(self):
        """Build sidebar and main area."""
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # --- Sidebar ---
        self.sidebar = ctk.CTkFrame(self, width=SIDEBAR_WIDTH, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nswe")
        self.sidebar.grid_propagate(False)
        self.sidebar.grid_rowconfigure(5, weight=1)
        self.sidebar.grid_columnconfigure(0, weight=1)

        # Create all UI elements FIRST
        self.header_label = ctk.CTkLabel(
            self.sidebar,
            text="💬 AI Fitness Coach",
            font=ctk.CTkFont(size=18, weight="bold"),
            anchor="center"
        )
        self.header_label.grid(row=0, column=0, padx=20, pady=(20, 10), sticky="ew")

        self.new_chat_button = ctk.CTkButton(
            self.sidebar,
            text="➕ New Chat",
            height=45,
            font=ctk.CTkFont(size=14, weight="bold"),
            corner_radius=8,
            command=self.show_welcome_screen
        )
        self.new_chat_button.grid(row=1, column=0, padx=15, pady=(5, 10), sticky="ew")

        # Voice Input Button
        self.voice_button = ctk.CTkButton(
            self.sidebar,
            text="🎙️ Speak Goal",
            height=40,
            font=ctk.CTkFont(size=13),
            corner_radius=8,
            command=self.start_voice_input
        )
        self.voice_button.grid(row=2, column=0, padx=15, pady=(0, 10), sticky="ew")

        # Export Button
        self.export_button = ctk.CTkButton(
            self.sidebar,
            text="📥 Export Plan",
            height=40,
            font=ctk.CTkFont(size=13),
            corner_radius=8,
            command=self.export_chat
        )
        self.export_button.grid(row=3, column=0, padx=15, pady=(0, 20), sticky="ew")

        # Theme Toggle
        self.theme_button = ctk.CTkButton(
            self.sidebar,
            text="🌞 Toggle Theme",
            height=35,
            font=ctk.CTkFont(size=12),
            corner_radius=8,
            command=self.toggle_theme
        )
        self.theme_button.grid(row=4, column=0, padx=15, pady=(0, 20), sticky="ew")
        self.history_label = ctk.CTkLabel(
            self.sidebar,
            text="🗂 Previous Chats"
        )
        self.history_label.grid(row=6, column=0, pady=(10,0))

        self.history_frame = ctk.CTkScrollableFrame(
            self.sidebar,
            height=150
        )
        self.history_frame.grid(row=7, column=0, padx=10, sticky="ew")

        # Static fitness tip
        tip_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        tip_frame.grid(row=5, column=0, sticky="sw", padx=20, pady=20)
        tip_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            tip_frame,
            text="🔥 Quick Tip",
            font=ctk.CTkFont(size=14, weight="bold")
        ).grid(row=0, column=0, sticky="w", pady=(0, 5))

        ctk.CTkLabel(
            tip_frame,
            text="Drink water before meals — it helps control appetite and boost metabolism!",
            font=ctk.CTkFont(size=13),
            justify="left",
            wraplength=SIDEBAR_WIDTH - 60
        ).grid(row=1, column=0, sticky="w")

        # --- Main Area ---
        self.main_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.main_frame.grid(row=0, column=1, padx=MAIN_AREA_PAD, pady=MAIN_AREA_PAD, sticky="nswe")
        self.main_frame.grid_rowconfigure(1, weight=1)
        self.main_frame.grid_columnconfigure(0, weight=1)

        # ✅ NOW apply theme — after all widgets are created
        self.apply_theme()

    def apply_theme(self):
        colors = DARK_COLORS if current_theme == "dark" else LIGHT_COLORS
        ctk.set_appearance_mode(current_theme)

        # Apply colors — only if widget exists
        if hasattr(self, 'sidebar'):
            self.sidebar.configure(fg_color=colors['sidebar_bg'])
        if hasattr(self, 'header_label'):
            self.header_label.configure(text_color=colors['header_text'])
        if hasattr(self, 'new_chat_button'):
            self.new_chat_button.configure(fg_color=colors['new_chat_bg'], hover_color=colors['new_chat_hover'])
        if hasattr(self, 'voice_button'):
            self.voice_button.configure(fg_color=colors['chat_item_bg'], hover_color=colors['chat_item_hover'])
        if hasattr(self, 'export_button'):
            self.export_button.configure(fg_color=colors['chat_item_bg'], hover_color=colors['chat_item_hover'])
        if hasattr(self, 'theme_button'):
            self.theme_button.configure(fg_color=colors['chat_item_bg'], hover_color=colors['chat_item_hover'])

    def toggle_theme(self):
        global current_theme
        current_theme = "light" if current_theme == "dark" else "dark"
        self.apply_theme()
        # Refresh current UI if in chat
        if self.current_session and hasattr(self.current_session.widgets.get('chat_container', None), 'master'):
            self.refresh_chat_ui()

    def refresh_chat_ui(self):
        """Rebuild current chat UI with new theme."""
        if not self.current_session:
            return
        session = self.current_session
        for widget in self.main_frame.winfo_children():
            widget.destroy()

        # Rebuild chat container
        self.main_frame.grid_rowconfigure(0, weight=1)

        self.chat_container = ctk.CTkScrollableFrame(
            self.main_frame,
            corner_radius=10,
            height=600
        )

        self.chat_container.grid(
            row=0,
            column=0,
            sticky="nsew",
            padx=5,
            pady=5
        )

        self.chat_container.grid(row=0, column=0, sticky="nswe", padx=5, pady=5)
        self.chat_container.grid_columnconfigure(0, weight=1)

        input_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        input_frame.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        input_frame.grid_columnconfigure(0, weight=1)

        colors = DARK_COLORS if current_theme == "dark" else LIGHT_COLORS

        user_entry = ctk.CTkEntry(
            input_frame,
            placeholder_text="Type a message...",
            height=50,
            font=ctk.CTkFont(size=14),
            corner_radius=25,
            border_width=0,
            fg_color=colors['entry_bg']
        )
        user_entry.grid(row=0, column=0, ipady=8, padx=(0, 10), sticky="ew")
        user_entry.bind("<Return>", lambda e: self.send_message(session))

        send_button = ctk.CTkButton(
            input_frame,
            text="➤",
            width=60,
            height=50,
            font=ctk.CTkFont(size=16, weight="bold"),
            corner_radius=25,
            fg_color=colors['user_bubble'],
            command=lambda: self.send_message(session)
        )
        send_button.grid(row=0, column=1)

        self.current_session.widgets.clear()
        self.current_session.widgets['chat_container'] = self.chat_container
        self.current_session.widgets['user_entry'] = user_entry
        self.current_session.widgets['send_button'] = send_button

        # Re-render messages
        for msg in session.history:
            if msg['role'] == 'system':
                continue
            sender = "You" if msg['role'] == 'user' else "Chatbot"
            self.append_message(session, sender, msg['content'])

    def show_welcome_screen(self):
        """Always show welcome screen with suggestions — no history."""
        for widget in self.main_frame.winfo_children():
            widget.destroy()

        welcome_container = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        welcome_container.pack(expand=True, fill="both", padx=30, pady=30)

        colors = DARK_COLORS if current_theme == "dark" else LIGHT_COLORS

        ctk.CTkLabel(
            welcome_container,
            text="👋 Welcome to Your AI Fitness Coach",
            font=ctk.CTkFont(size=26, weight="bold"),
            text_color=colors['text']
        ).pack(pady=(0, 15))

        ctk.CTkLabel(
            welcome_container,
            text="I'm here to help you crush your fitness goals. Let's start by understanding your needs!",
            font=ctk.CTkFont(size=15),
            text_color="#cccccc" if current_theme == "dark" else "#555555",
            wraplength=WINDOW_WIDTH - 100,
            justify="center"
        ).pack(pady=(0, 30))

        suggestions_frame = ctk.CTkFrame(welcome_container, fg_color="transparent")
        suggestions_frame.pack(fill="x", pady=10)

        suggestions = [
            "🍽️ Meal plan for weight loss",
            "💪 Workout plan for muscle gain",
            "🏖️ Summer beach-body challenge",
            "🏃‍♀️ Beginner running program",
            "🥗 Vegetarian diet plan",
            "🧘‍♂️ Stress-relief & mobility routine"
        ]

        for i, text in enumerate(suggestions):
            btn = ctk.CTkButton(
                suggestions_frame,
                text=text,
                height=45,
                font=ctk.CTkFont(size=14),
                fg_color=colors['chat_item_bg'],
                hover_color=colors['chat_item_hover'],
                corner_radius=12,
                command=lambda t=text: self.start_chat_with_suggestion(t)
            )
            btn.grid(row=i//2, column=i%2, padx=10, pady=8, sticky="ew")

        suggestions_frame.grid_columnconfigure(0, weight=1)
        suggestions_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            welcome_container,
            text="— or —",
            font=ctk.CTkFont(size=14),
            text_color="gray"
        ).pack(pady=20)

        prompt_entry = ctk.CTkEntry(
            welcome_container,
            placeholder_text="Type your goal here... e.g., 'I want to lose 10kg in 2 months'",
            height=50,
            font=ctk.CTkFont(size=14),
            corner_radius=25,
            border_width=0,
            fg_color=colors['entry_bg']
        )
        prompt_entry.pack(fill="x", padx=40, pady=(0, 20))
        prompt_entry.bind("<Return>", lambda e: self.start_chat_with_message(prompt_entry.get()))

        send_btn = ctk.CTkButton(
            welcome_container,
            text="🚀 Start Coaching",
            height=50,
            font=ctk.CTkFont(size=15, weight="bold"),
            fg_color=colors['user_bubble'],
            hover_color="#007acc" if current_theme == "dark" else "#1976D2",
            corner_radius=25,
            command=lambda: self.start_chat_with_message(prompt_entry.get())
        )
        send_btn.pack(pady=(0, 20))

        ctk.CTkLabel(
            welcome_container,
            text=f"Running locally using {OLLAMA_MODEL} via Ollama",
            font=ctk.CTkFont(size=11),
            text_color="gray"
        ).pack(pady=(30, 0))

    def start_chat_with_suggestion(self, suggestion_text):
        """Start fresh chat with suggestion."""
        self._start_fresh_chat()
        self.after(100, lambda: self._send_initial_message(suggestion_text))

    def start_chat_with_message(self, user_message):
        """Start fresh chat with custom message."""
        if not user_message.strip():
            return
        self._start_fresh_chat()
        self.after(100, lambda: self._send_initial_message(user_message))

    def _start_fresh_chat(self):
        """Create brand new session — no history carried over."""
        # Clear main area
        for widget in self.main_frame.winfo_children():
            widget.destroy()

        # Configure layout so chat fills available space
        self.main_frame.grid_rowconfigure(0, weight=1)
        self.main_frame.grid_rowconfigure(1, weight=0)
        self.main_frame.grid_columnconfigure(0, weight=1)

        # New session
        self.current_session = ChatSession("Active Chat")
        self.current_session.history.append({
            'role': 'system',
            'content': SYSTEM_PROMPT
        })

        colors = DARK_COLORS if current_theme == "dark" else LIGHT_COLORS

        # ---------------- Chat Container ----------------
        self.chat_container = ctk.CTkScrollableFrame(
            self.main_frame,
            corner_radius=10
        )

        self.chat_container.grid(
            row=0,
            column=0,
            sticky="nsew",
            padx=5,
            pady=5
        )

        self.chat_container.grid_columnconfigure(0, weight=1)

        # ---------------- Input Area ----------------
        input_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        input_frame.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        input_frame.grid_columnconfigure(0, weight=1)

        user_entry = ctk.CTkEntry(
            input_frame,
            placeholder_text="Type a message...",
            height=50,
            font=ctk.CTkFont(size=14),
            corner_radius=25,
            border_width=0,
            fg_color=colors['entry_bg']
        )
        user_entry.grid(row=0, column=0, ipady=8, padx=(0, 10), sticky="ew")
        user_entry.bind("<Return>", lambda e: self.send_message(self.current_session))

        send_button = ctk.CTkButton(
            input_frame,
            text="➤",
            width=60,
            height=50,
            font=ctk.CTkFont(size=16, weight="bold"),
            corner_radius=25,
            fg_color=colors['user_bubble'],
            command=lambda: self.send_message(self.current_session)
        )
        send_button.grid(row=0, column=1)

        # Store widget references safely
        self.current_session.widgets.clear()
        self.current_session.widgets['chat_container'] = self.chat_container
        self.current_session.widgets['user_entry'] = user_entry
        self.current_session.widgets['send_button'] = send_button

        # ---------------- Welcome Messages ----------------
        self.append_message(
            self.current_session,
            "Chatbot",
            "Hey there! 👋 I'm your AI Fitness Coach."
        )

        self.append_message(
            self.current_session,
            "Chatbot",
            "Ask me for workout plans, diet tips, or goal strategies — "
            "I'm here to help you get stronger, leaner, and healthier. "
            "Let's crush it together! 💪"
        )

    def append_message(self, session, sender, message):
        """Add a properly aligned message bubble."""
        container = getattr(self, "chat_container", None)

        if container is None:
            return

        msg_frame = ctk.CTkFrame(container, fg_color="transparent")
        msg_frame.pack(fill="x", padx=10, pady=4)

        colors = DARK_COLORS if current_theme == "dark" else LIGHT_COLORS
        bubble_color = colors['user_bubble'] if sender == "You" else colors['ai_bubble']
        text_color = colors['text']
        align = "e" if sender == "You" else "w"
        justify = "right" if sender == "You" else "left"

        timestamp = datetime.now().strftime("%H:%M")
        display_text = f"{message}\n\n{timestamp}"

        label = ctk.CTkLabel(
            msg_frame,
            text=display_text,
            font=ctk.CTkFont(size=14),
            text_color=text_color,
            fg_color=bubble_color,
            padx=15,
            pady=10,
            corner_radius=12,
            wraplength=int(self.winfo_width()*0.65),
            justify=justify
        )

        label.pack(side="top", anchor=align)

        if sender == "Chatbot":
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
        self.append_message(session, "Chatbot", "💭 Thinking...")
        session.current_ai_label.configure(text="💭 Thinking...")
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

        except ollama.ResponseError as e:
            error_msg = f"❌ Ollama Error: {e}\nIs the server running?"
            self.message_queue.put(('error', session, error_msg))
            if session.history and session.history[-1]['role'] == 'user':
                session.history.pop()
        except Exception as e:
            error_msg = f"⚠️ Unexpected error: {e}"
            self.message_queue.put(('error', session, error_msg))
            if session.history and session.history[-1]['role'] == 'user':
                session.history.pop()

    def check_message_queue(self):
        try:
            while True:
                msg_type, session, content = self.message_queue.get_nowait()

                if msg_type == 'chunk' and session == self.current_session:
                    if session.current_ai_label:
                        if "Thinking..." in session.current_ai_label.cget("text"):
                            session.current_ai_label.configure(text="")

                        current_text = session.current_ai_label.cget("text")
                        session.current_ai_label.configure(text=current_text + content)

                        session.widgets['chat_container'].update_idletasks()
                        session.widgets['chat_container']._parent_canvas.yview_moveto(1.0)
                        session.widgets['chat_container']._parent_canvas.yview_scroll(5,"units")


                elif msg_type == 'complete':
                    session.history.append({'role': 'assistant', 'content': content})
                    self.save_chat_session(session)
                    self.load_chat_buttons()

                    session.current_ai_label = None

                    entry = session.widgets['user_entry']
                    btn = session.widgets['send_button']
                    entry.configure(state="normal")
                    btn.configure(state="normal")
                    entry.focus_set()


        except queue.Empty:
            pass
        finally:
            self.after(50, self.check_message_queue)

    def _send_initial_message(self, message):
        if not self.current_session:
            return
        entry = self.current_session.widgets['user_entry']
        entry.delete(0, tk.END)
        entry.insert(0, message)
        self.send_message(self.current_session)

    # --- VOICE INPUT ---
    def start_voice_input(self):
        """Start listening for voice input in a background thread."""
        threading.Thread(target=self.listen_to_voice, daemon=True).start()

    def listen_to_voice(self):
        recognizer = sr.Recognizer()
        mic = sr.Microphone()

        try:
            self.voice_button.configure(text="🎤 Listening...", state="disabled")
            self.update()

            with mic as source:
                recognizer.adjust_for_ambient_noise(source, duration=0.5)
                audio = recognizer.listen(source, timeout=5, phrase_time_limit=10)

            self.voice_button.configure(text="🎙️ Processing...", state="disabled")
            self.update()

            text = recognizer.recognize_google(audio)
            self.voice_button.configure(text="🎙️ Speak Goal", state="normal")

            # Auto-start chat with recognized text
            self.start_chat_with_message(text)

        except sr.WaitTimeoutError:
            self.voice_button.configure(text="🎙️ Speak Goal", state="normal")
            self.show_toast("Timeout: No speech detected.")
        except sr.UnknownValueError:
            self.voice_button.configure(text="🎙️ Speak Goal", state="normal")
            self.show_toast("Could not understand audio.")
        except Exception as e:
            self.voice_button.configure(text="🎙️ Speak Goal", state="normal")
            self.show_toast(f"Error: {str(e)}")

    def show_toast(self, message):
        toast = ctk.CTkToplevel(self)
        toast.title("Message")
        toast.geometry("300x100")
        toast.attributes("-topmost", True)
        toast.resizable(False, False)

        label = ctk.CTkLabel(toast, text=message, font=ctk.CTkFont(size=13), wraplength=280)
        label.pack(expand=True, padx=20, pady=20)

        toast.after(3000, toast.destroy)

    # --- EXPORT CHAT ---
    def export_chat(self):
        """
        Export current chat to a .pdf file using the reportlab library.
        
        Note: This requires the 'reportlab' library. Install it with:
        `pip install reportlab`
        """
        if not self.current_session or len(self.current_session.history) <= 1:
            self.show_toast("No chat to export!")
            return

        # Create export directory if it doesn't exist
        export_dir = "exported_plans"
        os.makedirs(export_dir, exist_ok=True)

        # Generate filename with .pdf extension
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"fitness_plan_{timestamp}.pdf"
        filepath = os.path.join(export_dir, filename)

        try:
            # Create a SimpleDocTemplate to build the PDF
            doc = SimpleDocTemplate(filepath, pagesize=letter)
            story = []  # A list to hold the document's flowable content

            # Get the standard reportlab styles
            styles = getSampleStyleSheet()

            # Add a title and timestamp
            title_style = ParagraphStyle('Title', parent=styles['Normal'],
                                         fontSize=18, spaceAfter=12,
                                         alignment=TA_CENTER)
            story.append(Paragraph("AI FITNESS COACH PLAN", title_style))
            
            export_date_style = ParagraphStyle('ExportDate', parent=styles['Normal'],
                                               fontSize=10, spaceAfter=12)
            story.append(Paragraph(f"Exported on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", export_date_style))
            story.append(Spacer(1, 0.2 * inch))

            # Define a style for the chat messages
            user_style = ParagraphStyle('User', parent=styles['Normal'],
                                        fontSize=11, leading=14)
            coach_style = ParagraphStyle('Coach', parent=styles['Normal'],
                                         fontSize=11, leading=14)

            # Iterate through the chat history and add messages to the story
            for msg in self.current_session.history:
                if msg['role'] == 'system': 
                    continue
                
                role = "YOU" if msg['role'] == 'user' else "COACH"
                content = f"<b>[{role}]:</b> {msg['content']}"
                
                # Use different styles for user and coach messages
                if role == "YOU":
                    story.append(Paragraph(content, user_style))
                else:
                    story.append(Paragraph(content, coach_style))
                
                # Add a small spacer after each message
                story.append(Spacer(1, 0.1 * inch))

            # Build the PDF document from the story
            doc.build(story)

            self.show_toast(f"✅ Saved to:\n{filepath}")
        except Exception as e:
            self.show_toast(f"❌ Export failed: {str(e)}")
            
    def load_chat_buttons(self):

        for widget in self.history_frame.winfo_children():
            widget.destroy()

        files = sorted(os.listdir(CHAT_DIR), reverse=True)

        for file in files:

            row = ctk.CTkFrame(self.history_frame, fg_color="transparent")
            row.pack(fill="x", pady=2)

            # Open Chat Button
            open_btn = ctk.CTkButton(
                row,
                text=file.replace(".json",""),
                height=30,
                anchor="w",
                command=lambda f=file: self.load_chat(f)
            )
            open_btn.pack(side="left", fill="x", expand=True)

            # Delete Button
            del_btn = ctk.CTkButton(
                row,
                text="🗑",
                width=32,
                height=30,
                fg_color="#aa3333",
                hover_color="#cc4444",
                command=lambda f=file: self.delete_chat(f)
            )
            del_btn.pack(side="right", padx=2)

    def save_chat_session(self, session):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = os.path.join(CHAT_DIR, f"{timestamp}.json")

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(session.history, f, indent=2)
    
    def load_chat(self, filename):
        filepath = os.path.join(CHAT_DIR, filename)

        with open(filepath, "r") as f:
            history = json.load(f)

        self._start_fresh_chat()
        self.current_session.history = history
        self.refresh_chat_ui()
    
    def delete_chat(self, filename):
        filepath = os.path.join(CHAT_DIR, filename)

        try:
            os.remove(filepath)
            self.load_chat_buttons()

            # If currently viewing this chat → reset UI
            if self.current_session:
                self.show_welcome_screen()

        except Exception as e:
            self.show_toast(f"Delete failed: {e}")


csv_files = [
    'daily_food_nutrition_dataset.csv',
    'ehact_2014.csv',
    'food.csv',
    'Indian_Food_Nutrition_Processed.csv',
    'megaGymDataset.csv',
    'met.csv'
]
csv_folders = [
    'FoodData_Central_foundation_food_csv_2025-04-24',
    'Duke-Source-CSV',
    'FoodData_Central_sr_legacy_food_csv_2018-04',
    'FoodData_Central_survey_food_csv_2024-10-31'
]
training_file_path = 'training_data.jsonl'

def format_row_for_training(row):
    try:
        if 'Food_Item' in row and 'Calories' in row:
            prompt = f"How many calories are in {row['Food_Item']}?"
            response = f"{row['Food_Item']} has {row['Calories']} calories."
            return {"prompt": prompt, "response": response}
        elif 'Title' in row and 'Desc' in row:
            prompt = f"What is the workout '{row['Title']}'?"
            response = f"The workout '{row['Title']}' is described as: {row['Desc']}"
            return {"prompt": prompt, "response": response}
        elif 'Name' in row and 'Ingredients' in row:
            prompt = f"What ingredients are in {row['Name']}?"
            response = f"The ingredients for {row['Name']} are: {row['Ingredients']}"
            return {"prompt": prompt, "response": response}
    except Exception as e:
        print(f"Skipping row due to error: {e} - Row: {row}")
        return None

def main_training():
    all_dataframes = []
    print("Loading individual files...")
    for f in csv_files:
        try:
            df = pd.read_csv(f)
            df['source_file'] = f
            all_dataframes.append(df)
            print(f"  - Loaded {f} ({len(df)} rows)")
        except FileNotFoundError:
            print(f"  - WARNING: File not found, skipping: {f}")
        except Exception as e:
            print(f"  - ERROR loading {f}: {e}")
    print("\nLoading files from folders...")
    for folder in csv_folders:
        folder_path = os.path.join(os.getcwd(), folder)
        if not os.path.isdir(folder_path):
            print(f"  - WARNING: Folder not found, skipping: {folder}")
            continue
        folder_csvs = glob.glob(os.path.join(folder_path, '*.csv'))
        print(f"  - Found {len(folder_csvs)} CSVs in {folder}:")
        for f in folder_csvs:
            try:
                df = pd.read_csv(f)
                df['source_file'] = f
                all_dataframes.append(df)
                print(f"    - Loaded {os.path.basename(f)} ({len(df)} rows)")
            except Exception as e:
                print(f"    - ERROR loading {f}: {e}")
    if not all_dataframes:
        print("\nNo data was loaded. Exiting.")
        return
    print("\nCombining all dataframes...")
    combined_df = pd.concat(all_dataframes, ignore_index=True)
    print(f"Total rows from all sources: {len(combined_df)}")
    print(f"\nFormatting data for training... this may take a while.")
    formatted_data = combined_df.apply(format_row_for_training, axis=1)
    formatted_data = formatted_data.dropna().tolist()
    if not formatted_data:
        print("\n** ERROR: No data was formatted! ***")
        print("This likely means the column names in your format_row_for_training function are incorrect.")
        print("Please inspect your CSVs and update the function.")
        return
    print(f"\nSaving {len(formatted_data)} formatted entries to {training_file_path}...")
    with open(training_file_path, 'w', encoding='utf-8') as f:
        for item in formatted_data:
            f.write(json.dumps(item) + '\n')

if __name__ == "__main__":
    print("🚀 Starting AI Fitness Coach...")
    print("💡 Run 'ollama serve' in terminal.")
    print(f"🤖 Model: {OLLAMA_MODEL}")
    print("=" * 50)
    app = ChatbotApp()
    app.mainloop()