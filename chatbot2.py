import customtkinter as ctk
import ollama
import threading
import queue
import tkinter as tk

# --- Configuration ---
OLLAMA_MODEL = "llama3"
WINDOW_WIDTH = 1000
WINDOW_HEIGHT = 700
SIDEBAR_WIDTH = 260
MAIN_AREA_PAD = 20

# Colors
NEW_CHAT_BG = "#00a86b"
NEW_CHAT_HOVER = "#00885b"
CHAT_ITEM_BG = "#2d2d30"
CHAT_ITEM_HOVER = "#3c3c40"
SELECTED_BG = "#0084ff"
USER_BUBBLE_COLOR = "#0084ff"
AI_BUBBLE_COLOR = "#383838"
TEXT_COLOR = "#ffffff"

# Font
DEFAULT_FONT = ("Segoe UI", 14)


class ChatSession:
    def __init__(self, name):
        self.name = name
        self.history = []
        self.widgets = {}
        self.button = None
        self.is_selected = False
        self.current_ai_label = None  # Track the label being streamed into


class ChatbotApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("🧠 Workout & Diet AI Coach")
        self.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
        self.resizable(True, True)

        self.chat_sessions = []
        self.current_session = None
        self.message_queue = queue.Queue()

        self.setup_ui()
        self.new_chat()

        self.after(100, self.check_message_queue)

    def setup_ui(self):
        """Build sidebar and main area."""
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # --- Sidebar ---
        self.sidebar = ctk.CTkFrame(self, width=SIDEBAR_WIDTH, corner_radius=0, fg_color="#212121")
        self.sidebar.grid(row=0, column=0, sticky="nswe")
        self.sidebar.grid_propagate(False)
        self.sidebar.grid_rowconfigure(2, weight=1)
        self.sidebar.grid_columnconfigure(0, weight=1)

        self.header_label = ctk.CTkLabel(
            self.sidebar,
            text="💬 AI Fitness Coach",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=TEXT_COLOR,
            anchor="center"
        )
        self.header_label.grid(row=0, column=0, padx=20, pady=(20, 10), sticky="ew")

        self.new_chat_button = ctk.CTkButton(
            self.sidebar,
            text="➕ New Chat",
            height=45,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color=NEW_CHAT_BG,
            hover_color=NEW_CHAT_HOVER,
            corner_radius=8,
            command=self.new_chat
        )
        self.new_chat_button.grid(row=1, column=0, padx=15, pady=(5, 10), sticky="ew")

        self.chat_list_frame = ctk.CTkScrollableFrame(
            self.sidebar,
            fg_color="transparent",
            width=SIDEBAR_WIDTH - 40
        )
        self.chat_list_frame.grid(row=2, column=0, padx=10, pady=0, sticky="nswe")
        self.chat_list_frame.grid_columnconfigure(0, weight=1)

        # --- Main Area ---
        self.main_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.main_frame.grid(row=0, column=1, padx=MAIN_AREA_PAD, pady=MAIN_AREA_PAD, sticky="nswe")
        self.main_frame.grid_rowconfigure(1, weight=1)
        self.main_frame.grid_columnconfigure(0, weight=1)

        self.show_welcome_screen()

    def show_welcome_screen(self):
        for widget in self.main_frame.winfo_children():
            widget.destroy()

        welcome_container = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        welcome_container.pack(expand=True)

        ctk.CTkLabel(
            welcome_container,
            text="Welcome to Your AI Fitness Coach",
            font=ctk.CTkFont(size=24, weight="bold"),
            text_color="#00a86b"
        ).pack(pady=10)

        ctk.CTkLabel(
            welcome_container,
            text="I can help you with:\n\n• Workout Plans\n• Diet & Nutrition\n• Weight Loss or Muscle Gain Goals\n• Personalized Coaching",
            font=ctk.CTkFont(size=14),
            text_color="gray",
            justify="left"
        ).pack(pady=20)

        ctk.CTkLabel(
            welcome_container,
            text=f"Running locally using {OLLAMA_MODEL} via Ollama",
            font=ctk.CTkFont(size=12),
            text_color="gray"
        ).pack(pady=5)

    def new_chat(self):
        chat_num = len(self.chat_sessions) + 1
        chat_name = f"New Chat {chat_num}"
        session = ChatSession(chat_name)
        self.chat_sessions.append(session)

        btn = ctk.CTkButton(
            self.chat_list_frame,
            text=chat_name,
            height=40,
            font=ctk.CTkFont(size=13),
            anchor="w",
            fg_color=CHAT_ITEM_BG,
            hover_color=CHAT_ITEM_HOVER,
            corner_radius=6
        )
        btn.grid(sticky="ew", padx=5, pady=4)
        session.button = btn

        btn.configure(command=lambda s=session: self.switch_chat(s))
        self.switch_chat(session)

        self.append_message(session, "Chatbot", "Hello! I'm your personal AI fitness coach. 💪")
        self.append_message(session, "Chatbot", "Tell me about your goals, and I'll help you build a plan.")

    def switch_chat(self, session):
        if self.current_session:
            self.current_session.button.configure(fg_color=CHAT_ITEM_BG)
            self.current_session.is_selected = False

        session.button.configure(fg_color=SELECTED_BG)
        session.is_selected = True
        self.current_session = session

        for widget in self.main_frame.winfo_children():
            widget.destroy()

        # --- Chat Container (Scrollable) ---
        self.chat_container = ctk.CTkScrollableFrame(
            self.main_frame,
            fg_color="#1f1f1f",
            corner_radius=10
        )
        self.chat_container.grid(row=0, column=0, sticky="nswe", padx=5, pady=5)
        self.chat_container.grid_columnconfigure(0, weight=1)

        # Input Frame
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
            fg_color="#333333"
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
            fg_color=USER_BUBBLE_COLOR
        )
        send_button.grid(row=0, column=1)
        send_button.configure(command=lambda: self.send_message(session))

        session.widgets.update({
            'chat_container': self.chat_container,
            'user_entry': user_entry,
            'send_button': send_button
        })

        # Load existing messages
        for msg in session.history:
            sender = "You" if msg['role'] == 'user' else "Chatbot"
            self.append_message(session, sender, msg['content'])

    def append_message(self, session, sender, message):
        """Add a properly aligned message bubble."""
        container = session.widgets['chat_container']

        msg_frame = ctk.CTkFrame(container, fg_color="transparent")
        msg_frame.pack(fill="x", padx=10, pady=4)

        # Bubble style
        bubble_color = USER_BUBBLE_COLOR if sender == "You" else AI_BUBBLE_COLOR
        align = "e" if sender == "You" else "w"
        justify = "right" if sender == "You" else "left"

        label = ctk.CTkLabel(
            msg_frame,
            text=message,
            font=ctk.CTkFont(size=14),
            text_color="white",
            fg_color=bubble_color,
            padx=15,
            pady=10,
            corner_radius=12,
            wraplength=WINDOW_WIDTH // 2.5,
            justify=justify
        )
        label.pack(side="top", anchor=align)

        # Update chat tab name after first user message
        if sender == "You" and session.button.cget("text").startswith("New Chat"):
            short = (message.strip()[:20] + "...") if len(message.strip()) > 20 else message.strip()
            session.name = short
            session.button.configure(text=short)

        # If this is an AI message and we're starting a response, track it
        if sender == "Chatbot":
            session.current_ai_label = label  # Will be updated during streaming

    def send_message(self, session):
        user_text = session.widgets['user_entry'].get().strip()
        if not user_text:
            return

        # Disable input
        entry = session.widgets['user_entry']
        button = session.widgets['send_button']
        entry.configure(state="disabled")
        button.configure(state="disabled")

        # Show user message (right)
        self.append_message(session, "You", user_text)
        entry.delete(0, tk.END)

        # Add to history
        session.history.append({'role': 'user', 'content': user_text})

        # Start AI response: create a placeholder AI message (left)
        self.append_message(session, "Chatbot", "")  # Empty at first
        # Now the last label is the AI's — we'll stream into it

        # Start background thread
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
                    # Only update if we have an AI label to stream into
                    if session.current_ai_label:
                        current_text = session.current_ai_label.cget("text")
                        session.current_ai_label.configure(text=current_text + content)
                        # Scroll to bottom
                        session.widgets['chat_container']._parent_canvas.yview_moveto(1.0)

                elif msg_type == 'complete':
                    # Finalize history
                    session.history.append({'role': 'assistant', 'content': content})
                    # Clear the current AI label tracker after completion
                    session.current_ai_label = None

                    # Re-enable input
                    entry = session.widgets['user_entry']
                    btn = session.widgets['send_button']
                    entry.configure(state="normal")
                    btn.configure(state="normal")
                    entry.focus_set()

                elif msg_type == 'error':
                    # Remove the empty AI message and show error
                    if session.current_ai_label:
                        session.current_ai_label.destroy()
                        session.current_ai_label = None
                    self.append_message(session, "Error", content)
                    entry = session.widgets['user_entry']
                    btn = session.widgets['send_button']
                    entry.configure(state="normal")
                    btn.configure(state="normal")
                    entry.focus_set()

        except queue.Empty:
            pass
        finally:
            self.after(50, self.check_message_queue)


if __name__ == "__main__":
    print("🚀 Starting AI Fitness Coach...")
    print("💡 Run 'ollama serve' in terminal.")
    print(f"🤖 Model: {OLLAMA_MODEL}")
    print("=" * 50)

    app = ChatbotApp()
    app.mainloop()