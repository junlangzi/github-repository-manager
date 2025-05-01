import tkinter as tk
from tkinter import ttk, messagebox, filedialog, font as tkFont, simpledialog
import ttkbootstrap as tb
from ttkbootstrap.constants import *
import os
import shutil
import json
import threading
import queue
from github import Github, GithubException, UnknownObjectException
import platform # To get OS info for paths
import string # For drive letters
import subprocess # For opening files and potentially macOS/Linux icons later
import sys # For checking platform

# --- Cài đặt và Cấu hình ---
SETTINGS_FILE = "app_settings.json"
DEFAULT_SETTINGS = {
    "theme": "litera",
    "font_size": 10,
    "api_token": "", # Store raw token
    "show_icons": True # Setting to show/hide simple icons
}

# Hàng đợi để giao tiếp giữa luồng công việc và luồng GUI
update_queue = queue.Queue()

# --- Simple Icon Placeholders ---
FOLDER_ICON = "📁"
FILE_ICON = "📄"
# DRIVE_ICON = "💾" # Original
DRIVE_ICON = "💽" # Alt Drive Icon - often looks better

# --- Lớp xử lý GitHub API ---
class GitHubHandler:
    def __init__(self, token=None):
        self.g = None
        self.user = None
        self.authenticated_token = None # Track the token used for successful auth

        if token:
            try:
                self.g = Github(token)
                self.user = self.g.get_user()
                _ = self.user.login # Test connection
                print(f"Authenticated as: {self.user.login}")
                self.authenticated_token = token
            except GithubException as e:
                error_msg = f"Lỗi xác thực GitHub ({e.status}): {e.data.get('message', 'Unknown Error')}"
                print(error_msg)
                self.g = None
                self.user = None
            except Exception as e:
                error_msg = f"Lỗi kết nối GitHub không mong muốn: {e}"
                print(error_msg)
                self.g = None
                self.user = None

    def get_active_token(self):
        return self.authenticated_token

    def is_authenticated(self):
         # --- START CHANGE: Added self.user check ---
         return self.g is not None and self.user is not None and self.authenticated_token is not None
         # --- END CHANGE ---

    def get_repos(self):
        if not self.is_authenticated():
            return []
        try:
            return list(self.g.get_user().get_repos(type='all', sort='updated', direction='desc'))
        except Exception as e:
            messagebox.showerror("Lỗi lấy Repos", f"Không thể lấy danh sách repositories:\n{e}")
            return []

    def get_repo_contents(self, repo_name, path="", ref=None):
        if not self.is_authenticated():
            return None
        try:
            repo = self.user.get_repo(repo_name)
            if ref:
                contents = repo.get_contents(path, ref=ref)
            else:
                contents = repo.get_contents(path)
            return contents
        except UnknownObjectException:
            # This should ideally catch 404s, but we add a fallback below.
            print(f"Info: Path '{path}' in repo '{repo_name}' not found or repo root is empty (Specific UnknownObjectException 404).")
            return None # Return None, NO messagebox
        except GithubException as e:
            # Check specifically for 404 status within the general GithubException
            if e.status == 404:
                # Treat *any* 404 GithubException as "Not Found" or "Empty"
                print(f"Info: Path '{path}' in repo '{repo_name}' not found or repo root is empty (General GithubException 404). Status: {e.status}, Message: {e.data.get('message')}")
                return None # Return None WITHOUT showing the error messagebox for 404
            else:
                # For all *other* GithubExceptions (401, 403, 500, etc.), show the error
                messagebox.showerror("Lỗi GitHub", f"Không thể lấy nội dung repo '{repo_name}' tại path '{path}'.\nLỗi: {e.status} - {e.data.get('message', 'Unknown Error')}")
                return None # Return None after showing the error for non-404 issues
        except Exception as e:
            # Show errors for unexpected issues (network, etc.)
            messagebox.showerror("Lỗi không xác định", f"Đã xảy ra lỗi khi lấy nội dung repo:\n{e}")
            return None # Return None on general errors

    def delete_item(self, repo_name, path, sha, commit_message="Delete item via app"):
        if not self.is_authenticated():
            return False, "Chưa xác thực GitHub"
        try:
            repo = self.user.get_repo(repo_name)
            repo.delete_file(path, commit_message, sha)
            return True, f"Đã xóa thành công: {path}"
        except UnknownObjectException:
            return False, f"Lỗi: Item tại '{path}' không tìm thấy (có thể đã bị xóa)."
        except GithubException as e:
            msg = e.data.get('message', 'Unknown GitHub Error')
            if e.status == 409 and "must remove all files" in msg.lower():
                 return False, f"Lỗi: Không thể xóa thư mục không rỗng '{path}'. Vui lòng xóa nội dung bên trong trước."
            elif e.status == 404:
                 return False, f"Lỗi: Không tìm thấy item tại '{path}' để xóa (404)."
            else:
                return False, f"Lỗi GitHub khi xóa '{path}': {e.status} - {msg}"
        except Exception as e:
            return False, f"Lỗi không xác định khi xóa '{path}':\n{e}"

    def upload_file(self, repo_name, local_path, github_path, commit_message="Upload file via app", progress_callback=None, overwrite=False):
        if not self.is_authenticated():
            return False, "Chưa xác thực GitHub"

        try:
            # --- Get repo object ---
            repo = self.user.get_repo(repo_name)
            file_name = os.path.basename(local_path)
            clean_github_path = github_path.strip('/')
            target_path = f"{clean_github_path}/{file_name}" if clean_github_path else file_name

            # --- Step 1: Check if file exists on GitHub ---
            # This step might fail with 404 if repo is empty or path invalid
            existing_file_sha = None
            try:
                existing_file = repo.get_contents(target_path)
                existing_file_sha = existing_file.sha
                print(f"Info: File '{target_path}' exists (SHA: {existing_file_sha}).")
            except UnknownObjectException:
                # Expected case for new file or path in empty repo
                print(f"Info: File '{target_path}' not found (UnknownObjectException). Will create.")
                pass # File doesn't exist, proceed to create
            except GithubException as e:
                # Handle 404 within GithubException during check
                if e.status == 404:
                    # Treat general 404 during check as "file doesn't exist"
                    print(f"Info: File '{target_path}' not found (GithubException 404). Will create.")
                    pass # File doesn't exist, proceed to create
                else:
                    # For other Github errors during the check (e.g., 403 Forbidden), re-raise
                    print(f"Error: GitHub check failed for '{target_path}' with status {e.status}. Re-raising.")
                    raise e # Re-raise to be caught by the outer exception handler
            except Exception as e:
                 # Handle other unexpected errors during the check
                 print(f"Error: Unexpected error during existence check for '{target_path}': {e}. Re-raising.")
                 raise e # Re-raise

            # --- Step 2: Read local file content ---
            try:
                with open(local_path, "rb") as f:
                    content_bytes = f.read()
            except FileNotFoundError:
                 return False, f"Lỗi: Không tìm thấy file cục bộ '{local_path}'"
            except Exception as e:
                 return False, f"Lỗi đọc file cục bộ '{local_path}': {e}"

            # --- Step 3: Perform Create or Update API call ---
            status_msg = ""
            action_description = ""
            try:
                if existing_file_sha: # File exists, update or skip
                    action_description = "update"
                    if overwrite:
                        print(f"Action: Updating existing file: {target_path}")
                        repo.update_file(target_path, commit_message, content_bytes, existing_file_sha)
                        status_msg = f"Đã cập nhật file: {target_path}"
                    else:
                        print(f"Action: Skipping existing file (overwrite=False): {target_path}")
                        return False, "exists" # Special status for skipped overwrite
                else: # File does not exist, create it
                    action_description = "create"
                    print(f"Action: Creating new file: {target_path}")
                    repo.create_file(target_path, commit_message, content_bytes)
                    status_msg = f"Đã upload file mới: {target_path}"

                # If successful
                if progress_callback:
                     progress_callback(100)
                return True, status_msg

            except GithubException as e: # Catch GitHub errors *during* create/update
                 msg = e.data.get('message', f'Unknown GitHub Error during {action_description}')
                 print(f"Error: GitHub {action_description} failed for '{target_path}': {e.status} - {msg}")
                 # Return a specific error message indicating the failed operation
                 return False, f"Lỗi GitHub khi {action_description} file '{target_path}': {e.status} - {msg}"
            except Exception as e: # Catch other errors during create/update
                 print(f"Error: Unexpected error during {action_description} for '{target_path}': {e}")
                 return False, f"Lỗi không xác định khi {action_description} file '{target_path}':\n{e}"

        # --- Outer Exception Handling (for get_repo or re-raised check errors) ---
        except GithubException as e:
             msg = e.data.get('message', 'Unknown GitHub Error during setup')
             print(f"Error: GitHub setup error for upload to '{repo_name}': {e.status} - {msg}")
             return False, f"Lỗi GitHub (setup): {e.status} - {msg}"
        except Exception as e:
             print(f"Error: Generic error during upload setup to '{repo_name}': {e}")
             return False, f"Lỗi không xác định (setup): {e}"

# --- Lớp ứng dụng chính ---
class GitHubManagerApp:
    def __init__(self, root):
        self.root = root
        # Store previous state to check for changes requiring refresh
        self.previous_settings = {}
        self.settings = self.load_settings()
        self.github_handler = GitHubHandler(self.get_token())

        # Determine Initial Local Path
        initial_local_path = None # Default to "My Computer" view signal (None)
        desktop_path_found = False
        home_path = os.path.expanduser("~") # Get home path for final fallback

        try:
            quick_paths = self.get_quick_access_paths() # Call the method to get paths
            desktop_path = quick_paths.get("Màn hình nền") # Key from get_quick_access_paths

            if desktop_path and os.path.isdir(desktop_path):
                initial_local_path = desktop_path # Use Desktop path
                desktop_path_found = True
                print(f"Defaulting initial local view to Desktop: {initial_local_path}")
            else:
                print(f"Desktop path ('Màn hình nền') not found or invalid. Will use 'My Computer' view.")
        except Exception as e:
            print(f"Error determining Desktop path during initialization: {e}. Will use 'My Computer' view.")

        self.current_local_path = initial_local_path

        # Continue with other initializations
        self.clipboard = None
        self.upload_tasks = {}
        self.task_id_counter = 0
        self.current_github_context = {'repo': None, 'path': ""}

        # Drag and Drop State
        self._dnd_dragging = False
        self._dnd_start_x = 0
        self._dnd_start_y = 0
        self._dnd_source_widget = None
        self._dnd_items = None # Data being dragged

        # --- Initialize UI and other components ---
        self.setup_styles()      # Set up ttk styles and fonts
        self.create_widgets()    # Create all the visual elements (trees, buttons, etc.)
        self.apply_settings(force_refresh=True) # Apply theme, font size from settings

        # --- Populate Initial Views ---
        self.populate_local_tree(self.current_local_path)
        self.populate_github_tree()

        # Start the queue processor for background tasks
        self.process_queue()

        # Set up drag and drop bindings for the trees
        self.setup_drag_drop()

        print("GitHubManagerApp initialized.") # Confirmation message

    # --- Cài đặt & Style ---
    def load_settings(self):
        try:
            with open(SETTINGS_FILE, 'r') as f:
                loaded_settings = json.load(f)
                # Start with defaults, then update with loaded, ensuring all keys exist
                final_settings = DEFAULT_SETTINGS.copy()
                final_settings.update(loaded_settings)
                return final_settings
        except (FileNotFoundError, json.JSONDecodeError):
            return DEFAULT_SETTINGS.copy()

    def save_settings(self):
        try:
            with open(SETTINGS_FILE, 'w') as f:
                json.dump(self.settings, f, indent=4)
            print(f"Settings saved to {SETTINGS_FILE}")
            self.update_status("Đã lưu cài đặt.")
        except Exception as e:
            messagebox.showerror("Lỗi Lưu Cài Đặt", f"Không thể lưu file cài đặt:\n{e}")

    def get_token(self):
        return self.settings.get("api_token", "")

    def setup_styles(self):
        self.style = tb.Style()
        self.default_font = tkFont.nametofont("TkDefaultFont")
        self.update_font_size()

    def update_font_size(self):
        size = self.settings.get("font_size", 10)
        try:
            self.default_font.configure(size=size)
            row_height = int(size * 2.2) if size >= 10 else 22 # Min row height
            # Adjust Treeview font and row height
            self.style.configure("Treeview", font=(self.default_font.actual("family"), size), rowheight=row_height)
            # Adjust other common widgets
            self.style.configure("TLabel", font=(self.default_font.actual("family"), size))
            self.style.configure("TButton", font=(self.default_font.actual("family"), size))
            self.style.configure("TEntry", font=(self.default_font.actual("family"), size))
            self.style.configure("TCombobox", font=(self.default_font.actual("family"), size))
            self.style.configure("TCheckbutton", font=(self.default_font.actual("family"), size))
            self.style.configure("TLabelframe.Label", font=(self.default_font.actual("family"), size)) # Frame labels

            # Re-apply style to existing trees if they exist
            if hasattr(self, 'local_tree'):
                 self.local_tree.configure(style="Treeview")
            if hasattr(self, 'github_tree'):
                 self.github_tree.configure(style="Treeview")
        except tk.TclError as e:
            print(f"Error applying font size {size}: {e}")

    def apply_settings(self, force_refresh=False):
        # Store current settings before applying new ones
        self.previous_settings = self.settings.copy()

        # Apply Theme
        selected_theme = self.settings.get("theme", DEFAULT_SETTINGS["theme"])
        try:
            if selected_theme not in self.style.theme_names():
                 print(f"Warning: Theme '{selected_theme}' not found, falling back to default.")
                 selected_theme = DEFAULT_SETTINGS["theme"]
                 self.settings["theme"] = selected_theme # Correct the setting if invalid
            self.style.theme_use(selected_theme)
        except tk.TclError as e:
            print(f"Error applying theme '{selected_theme}': {e}. Using fallback.")
            try:
                 self.style.theme_use(DEFAULT_SETTINGS["theme"])
                 self.settings["theme"] = DEFAULT_SETTINGS["theme"]
            except tk.TclError as e_fallback:
                 print(f"FATAL: Could not apply default theme '{DEFAULT_SETTINGS['theme']}': {e_fallback}")

        # Apply Font Size (calls update_font_size internally)
        self.update_font_size()

        # Update Settings UI Elements
        if hasattr(self, 'theme_combobox') and self.theme_combobox.winfo_exists():
             current_theme = self.settings.get("theme", DEFAULT_SETTINGS["theme"])
             self.theme_combobox.set(current_theme if current_theme in self.theme_combobox['values'] else DEFAULT_SETTINGS["theme"])

        if hasattr(self, 'font_size_scale') and self.font_size_scale.winfo_exists():
            self.font_size_scale.set(self.settings.get("font_size", DEFAULT_SETTINGS["font_size"]))
            self.font_size_display_var.set(self.settings.get("font_size", DEFAULT_SETTINGS["font_size"])) # Ensure display var is also set

        if hasattr(self, 'api_token_entry') and self.api_token_entry.winfo_exists():
            current_token = self.get_token()
            display_value = "*******" if current_token else ""
            try:
                # Update only if the display value needs changing (avoid cursor jump)
                if self.api_token_entry.get() != display_value and self.api_token_entry['show'] == '*':
                    is_focused = self.root.focus_get() == self.api_token_entry
                    if not is_focused: # Avoid changing content while user might be typing
                        self.api_token_entry.delete(0, tk.END)
                        self.api_token_entry.insert(0, display_value)
                    else:
                        # If focused and masked, leave it as is unless it was empty
                        if not self.api_token_entry.get() and display_value:
                            self.api_token_entry.delete(0, tk.END)
                            self.api_token_entry.insert(0, display_value)

            except tk.TclError as e:
                 print(f"Error updating api_token_entry widget: {e}")

        # Apply Icon Setting
        if hasattr(self, 'show_icons_checkbutton') and self.show_icons_checkbutton.winfo_exists():
             self.show_icons_var.set(self.settings.get("show_icons", DEFAULT_SETTINGS["show_icons"]))

        # Check for changes requiring refresh
        refresh_needed = force_refresh or \
                         self.settings.get("show_icons") != self.previous_settings.get("show_icons")


        # Apply GitHub Token & Re-initialize Handler if needed
        token_from_settings = self.get_token()
        needs_reinit = False
        if not hasattr(self, 'github_handler') or self.github_handler is None:
            needs_reinit = bool(token_from_settings)
        elif not self.github_handler.is_authenticated() and token_from_settings:
            needs_reinit = True
        elif self.github_handler.is_authenticated() and self.github_handler.get_active_token() != token_from_settings:
            needs_reinit = True
        elif self.github_handler.is_authenticated() and not token_from_settings:
             needs_reinit = True

        if needs_reinit:
            print("Applying settings: Re-initializing GitHub Handler...")
            self.github_handler = GitHubHandler(token_from_settings)
            refresh_needed = True # Always refresh GitHub tree after re-auth

        # Perform refreshes if needed
        if refresh_needed:
            print("Settings changed requiring refresh...")
            if hasattr(self, 'local_tree'):
                self.populate_local_tree(self.current_local_path)
            if hasattr(self, 'github_tree'):
                self.populate_github_tree(self.current_github_context.get('repo'), self.current_github_context.get('path', ""))


    # --- Tạo Widgets ---
    def create_widgets(self):
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(expand=True, fill=BOTH, padx=5, pady=5)

        main_frame = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(main_frame, text=" Cửa sổ chính ")

        paned_window = ttk.PanedWindow(main_frame, orient=HORIZONTAL)
        paned_window.pack(expand=True, fill=BOTH)

        # --- Left Panel (Local) ---
        left_frame = ttk.Frame(paned_window, padding=5)
        paned_window.add(left_frame, weight=1)

        local_nav_frame = ttk.Frame(left_frame)
        local_nav_frame.pack(side=TOP, fill=X, pady=(0, 5))

        self.quick_nav_var = tk.StringVar()
        quick_nav_options = self.get_quick_access_paths()
        self.quick_nav_combo = ttk.Combobox(local_nav_frame, textvariable=self.quick_nav_var,
                                             values=list(quick_nav_options.keys()), state="readonly", width=15)
        self.quick_nav_combo.pack(side=LEFT, padx=(0, 5))
        self.quick_nav_combo.bind("<<ComboboxSelected>>", self.on_quick_nav_select)
        self.quick_nav_combo.set("Truy cập nhanh")

        self.local_path_var = tk.StringVar(value=self.current_local_path)
        local_path_entry = ttk.Entry(local_nav_frame, textvariable=self.local_path_var, state="normal")
        local_path_entry.pack(side=LEFT, fill=X, expand=True, padx=(0, 5))
        local_path_entry.bind("<Return>", self.navigate_local_from_entry)

        up_button = ttk.Button(local_nav_frame, text="Lên", command=self.go_up_local, style="Outline.TButton", width=5)
        up_button.pack(side=LEFT)

        local_tree_frame = ttk.Frame(left_frame)
        local_tree_frame.pack(expand=True, fill=BOTH)

        self.local_tree = ttk.Treeview(local_tree_frame, columns=("Type", "Size", "Modified"), show="tree headings", style="Treeview")
        self.local_tree.heading("#0", text="Tên", command=lambda: self.sort_treeview_column(self.local_tree, "#0", False))
        self.local_tree.heading("Type", text="Loại", command=lambda: self.sort_treeview_column(self.local_tree, "Type", False))
        self.local_tree.heading("Size", text="Kích thước", command=lambda: self.sort_treeview_column(self.local_tree, "Size", True))
        self.local_tree.heading("Modified", text="Ngày sửa", command=lambda: self.sort_treeview_column(self.local_tree, "Modified", False))

        self.local_tree.column("#0", stretch=tk.YES, width=250, anchor='w') # Increased width slightly for icons
        self.local_tree.column("Type", width=80, anchor='w')
        self.local_tree.column("Size", width=100, anchor='e')
        self.local_tree.column("Modified", width=130, anchor='e')

        local_vscroll = ttk.Scrollbar(local_tree_frame, orient=VERTICAL, command=self.local_tree.yview)
        local_hscroll = ttk.Scrollbar(left_frame, orient=HORIZONTAL, command=self.local_tree.xview)
        self.local_tree.configure(yscrollcommand=local_vscroll.set, xscrollcommand=local_hscroll.set)
        local_vscroll.pack(side=RIGHT, fill=Y)
        self.local_tree.pack(expand=True, fill=BOTH)
        local_hscroll.pack(side=BOTTOM, fill=X, pady=(5,0))

        self.local_tree.bind("<Double-1>", self.on_local_item_double_click)
        self.local_tree.bind("<Button-3>", self.show_local_context_menu)
        self.local_tree.bind("<Delete>", self.delete_selected_local_items)


        # --- Right Panel (GitHub) ---
        right_frame = ttk.Frame(paned_window, padding=5)
        paned_window.add(right_frame, weight=1)

        github_action_frame = ttk.Frame(right_frame)
        github_action_frame.pack(side=TOP, fill=X, pady=(0,5))
        refresh_gh_button = ttk.Button(github_action_frame, text="Làm mới GH", command=self.refresh_github_tree_current_view, style="Outline.TButton")
        refresh_gh_button.pack(side=RIGHT)

        self.github_path_label_var = tk.StringVar(value="GitHub:")
        github_path_label = ttk.Label(github_action_frame, textvariable=self.github_path_label_var, anchor='w')
        github_path_label.pack(side=LEFT, fill=X, expand=True)

        github_tree_frame = ttk.Frame(right_frame)
        github_tree_frame.pack(expand=True, fill=BOTH)

        self.github_tree = ttk.Treeview(github_tree_frame, columns=("Type", "Size", "Path"), show="tree headings", style="Treeview")
        self.github_tree.heading("#0", text="Tên", command=lambda: self.sort_treeview_column(self.github_tree, "#0", False))
        self.github_tree.heading("Type", text="Loại", command=lambda: self.sort_treeview_column(self.github_tree, "Type", False))
        self.github_tree.heading("Size", text="Kích thước", command=lambda: self.sort_treeview_column(self.github_tree, "Size", True))
        self.github_tree.heading("Path", text="Đường dẫn GitHub") # Keep this for internal use maybe

        self.github_tree.column("#0", stretch=tk.YES, width=250, anchor='w') # Increased width slightly for icons
        self.github_tree.column("Type", width=80, anchor='w')
        self.github_tree.column("Size", width=100, anchor='e')
        self.github_tree.column("Path", width=0, stretch=tk.NO, minwidth=0) # Hide Path column visually

        github_vscroll = ttk.Scrollbar(github_tree_frame, orient=VERTICAL, command=self.github_tree.yview)
        github_hscroll = ttk.Scrollbar(right_frame, orient=HORIZONTAL, command=self.github_tree.xview)
        self.github_tree.configure(yscrollcommand=github_vscroll.set, xscrollcommand=github_hscroll.set)
        github_vscroll.pack(side=RIGHT, fill=Y)
        self.github_tree.pack(expand=True, fill=BOTH)
        github_hscroll.pack(side=BOTTOM, fill=X, pady=(5,0))

        self.github_tree.bind("<Double-1>", self.on_github_item_double_click)
        self.github_tree.bind("<Button-3>", self.show_github_context_menu)
        self.github_tree.bind("<Delete>", self.delete_selected_github_items)

        # --- Status Bar ---
        status_frame = ttk.Frame(main_frame, padding=(5, 5))
        status_frame.pack(side=BOTTOM, fill=X)
        self.status_var = tk.StringVar(value="Sẵn sàng")
        status_label = ttk.Label(status_frame, textvariable=self.status_var, anchor=W)
        status_label.pack(side=LEFT, fill=X, expand=True)
        self.progress_bar = ttk.Progressbar(status_frame, orient=HORIZONTAL, length=200, mode='determinate')
        self.progress_bar.pack(side=RIGHT, padx=5)

        # --- Settings Tab ---
        settings_frame = ttk.Frame(self.notebook, padding=20)
        self.notebook.add(settings_frame, text=" Cài đặt ")

        # --- UI Settings Frame ---
        ui_frame = ttk.LabelFrame(settings_frame, text="Giao diện & Hiển thị", padding=10)
        ui_frame.pack(fill=X, pady=10)

        theme_frame = ttk.Frame(ui_frame) # No label frame needed inside outer label frame
        theme_frame.pack(fill=X, pady=(0, 5))
        theme_label = ttk.Label(theme_frame, text="Chọn Theme:")
        theme_label.pack(side=LEFT, padx=5, anchor='w')
        valid_themes = self.style.theme_names() if hasattr(self, 'style') else ["litera", "cosmo", "flatly", "journal", "lumen", "minty", "pulse", "sandstone", "united", "yeti", "superhero", "darkly", "cyborg", "vapor"]
        self.theme_combobox = ttk.Combobox(theme_frame, values=valid_themes, state="readonly")
        self.theme_combobox.pack(side=LEFT, padx=5, expand=True, fill=X)
        self.theme_combobox.bind("<<ComboboxSelected>>", self.on_theme_change)

        font_frame = ttk.Frame(ui_frame) # No label frame needed inside outer label frame
        font_frame.pack(fill=X, pady=5)
        font_label = ttk.Label(font_frame, text="Cỡ chữ:")
        font_label.pack(side=LEFT, padx=5, anchor='w')
        self.font_size_var_float = tk.DoubleVar(value=float(self.settings.get("font_size", 10)))
        self.font_size_scale = ttk.Scale(font_frame, from_=8, to=20, orient=HORIZONTAL, variable=self.font_size_var_float, command=self.on_font_size_change_live)
        self.font_size_scale.pack(side=LEFT, padx=5, expand=True, fill=X)
        self.font_size_display_var = tk.IntVar(value=self.settings.get("font_size", 10))
        font_value_label = ttk.Label(font_frame, textvariable=self.font_size_display_var, width=3)
        font_value_label.pack(side=LEFT, padx=5)

        # --- Icon Setting ---
        icon_frame = ttk.Frame(ui_frame)
        icon_frame.pack(fill=X, pady=(5, 0))
        self.show_icons_var = tk.BooleanVar(value=self.settings.get("show_icons", True))
        self.show_icons_checkbutton = ttk.Checkbutton(icon_frame, text="Hiển thị Icon đơn giản (📁/📄/💾)", variable=self.show_icons_var)
        self.show_icons_checkbutton.pack(side=LEFT, padx=5)

        # --- API Settings Frame ---
        api_frame = ttk.LabelFrame(settings_frame, text="GitHub API Token", padding=10)
        api_frame.pack(fill=X, pady=10)
        api_label = ttk.Label(api_frame, text="Personal Access Token:")
        api_label.pack(side=LEFT, padx=5)
        self.api_token_entry = ttk.Entry(api_frame, show="*")
        self.api_token_entry.pack(side=LEFT, padx=5, expand=True, fill=X)
        self.show_token_var = tk.BooleanVar(value=False)
        show_token_button = ttk.Checkbutton(api_frame, text="Hiện", variable=self.show_token_var, command=self.toggle_token_visibility, style='Toolbutton')
        show_token_button.pack(side=LEFT)

        save_button = ttk.Button(settings_frame, text="Lưu cài đặt & Áp dụng", command=self.save_settings_ui, style="success.TButton")
        save_button.pack(pady=20)

    # --- Sorting Logic for Treeview ---
    def sort_treeview_column(self, tv, col, is_numeric):
        """Sorts a treeview column alphabetically or numerically."""
        if not hasattr(self, 'sort_reverse') or col not in self.sort_reverse:
             if not hasattr(self, 'sort_reverse'): self.sort_reverse = {}
             self.sort_reverse[col] = False

        items = []
        for k in tv.get_children(''):
            try:
                if col == "#0":
                    # Use .item(iid, 'text') for the tree column (#0)
                    # Remove icon prefix for sorting if icons are enabled
                    text_val = tv.item(k, 'text')
                    if self.settings.get("show_icons"):
                        # Remove first char and space if it's one of the icons
                        if text_val.startswith(FOLDER_ICON + " ") or \
                           text_val.startswith(FILE_ICON + " ") or \
                           text_val.startswith(DRIVE_ICON + " "):
                            value = text_val[2:]
                        else:
                            value = text_val # Handle items without icons like '..'
                    else:
                        value = text_val
                else:
                    # Use .set(iid, column_id) for display columns
                    value = tv.set(k, col)
                items.append((value, k))
            except tk.TclError:
                print(f"Warning: Could not get data for item {k} while sorting column {col}. Skipping.")
                continue

        # Clear previous sort indicators
        for c in tv['columns'] + ('#0',):
             try:
                 heading_options = tv.heading(c)
                 if heading_options and 'text' in heading_options:
                     current_text = heading_options['text']
                     # Check if indicator exists before replacing
                     if ' ▲' in current_text or ' ▼' in current_text:
                         tv.heading(c, text=current_text.replace(' ▲', '').replace(' ▼', ''))
             except tk.TclError:
                 pass # Ignore if column disappears


        if is_numeric:
            def get_numeric_value(item_tuple):
                val_str = str(item_tuple[0]).split(' ')[0] # Ensure string conversion first
                try:
                    # Handle potential non-numeric values resulting from errors or empty fields
                    return float(val_str.replace(',', '')) # Allow for commas if any crept in
                except (ValueError, TypeError):
                    return -1 # Treat non-numeric/empty as smallest
            items.sort(key=get_numeric_value, reverse=self.sort_reverse[col])
        else:
            # Case-insensitive string sort
            items.sort(key=lambda x: str(x[0]).lower(), reverse=self.sort_reverse[col]) # Ensure string conversion

        # Rearrange items in treeview
        for index, (val, k) in enumerate(items):
            if tv.exists(k):
                 tv.move(k, '', index)
            else:
                 print(f"Warning: Item {k} disappeared before it could be moved during sort.")

        # Toggle sort direction for next click
        self.sort_reverse[col] = not self.sort_reverse[col]

        # Update heading indicator for the clicked column
        try:
            heading_options = tv.heading(col)
            if heading_options and 'text' in heading_options:
                 col_name = heading_options['text'] # Get potentially cleaned text
                 indicator = ' ▲' if not self.sort_reverse[col] else ' ▼'
                 tv.heading(col, text=f"{col_name}{indicator}")
        except tk.TclError:
             pass # Ignore errors updating heading if column vanished during sort

    # --- Helper for Quick Access Paths ---
    def get_quick_access_paths(self):
        """Returns a dictionary of display names and actual paths for quick access."""
        paths = {}
        home = os.path.expanduser("~")
        paths["Thư mục nhà"] = home

        # Platform specific Documents location
        docs = ""
        if platform.system() == "Windows":
            try:
                import ctypes
                from ctypes.wintypes import HWND, HANDLE, DWORD, LPCWSTR, MAX_PATH
                CSIDL_PERSONAL = 5 # My Documents
                SHGFP_TYPE_CURRENT = 0 # Get current, not default value
                buf = ctypes.create_unicode_buffer(MAX_PATH)
                ctypes.windll.shell32.SHGetFolderPathW(None, CSIDL_PERSONAL, None, SHGFP_TYPE_CURRENT, buf)
                docs = buf.value
            except Exception as e:
                print(f"Could not get Documents folder via API: {e}")
                docs = os.path.join(home, "Documents") # Fallback
        elif platform.system() == "Darwin":
             docs = os.path.join(home, "Documents")
        else: # Linux/Other
             docs = os.path.join(home, "Documents") # Common default
             if not os.path.isdir(docs): # XDG fallback
                 try:
                     xdg_docs = subprocess.check_output(['xdg-user-dir', 'DOCUMENTS'], text=True, stderr=subprocess.DEVNULL).strip()
                     if xdg_docs and os.path.isdir(xdg_docs):
                         docs = xdg_docs
                 except (FileNotFoundError, subprocess.CalledProcessError):
                     pass # xdg-user-dir not found or failed

        if os.path.isdir(docs): paths["Tài liệu"] = docs

        # Downloads folder (similar XDG logic for Linux)
        downloads = ""
        if platform.system() == "Windows":
            downloads = os.path.join(home, "Downloads")
        elif platform.system() == "Darwin":
             downloads = os.path.join(home, "Downloads")
        else: # Linux/Other
             downloads = os.path.join(home, "Downloads")
             if not os.path.isdir(downloads):
                 try:
                     xdg_downloads = subprocess.check_output(['xdg-user-dir', 'DOWNLOAD'], text=True, stderr=subprocess.DEVNULL).strip()
                     if xdg_downloads and os.path.isdir(xdg_downloads):
                         downloads = xdg_downloads
                 except (FileNotFoundError, subprocess.CalledProcessError):
                     pass
        if os.path.isdir(downloads): paths["Tải xuống"] = downloads

        # Desktop folder (similar XDG logic for Linux)
        desktop = ""
        if platform.system() == "Windows":
            desktop = os.path.join(home, "Desktop")
        elif platform.system() == "Darwin":
            desktop = os.path.join(home, "Desktop")
        else: # Linux/Other
             desktop = os.path.join(home, "Desktop")
             if not os.path.isdir(desktop):
                 try:
                     xdg_desktop = subprocess.check_output(['xdg-user-dir', 'DESKTOP'], text=True, stderr=subprocess.DEVNULL).strip()
                     if xdg_desktop and os.path.isdir(xdg_desktop):
                         desktop = xdg_desktop
                 except (FileNotFoundError, subprocess.CalledProcessError):
                     pass
        if os.path.isdir(desktop): paths["Màn hình nền"] = desktop


        # Add Drives/Volumes
        if platform.system() == "Windows":
            for letter in string.ascii_uppercase:
                drive = f"{letter}:\\"
                if os.path.isdir(drive):
                    volume_label = self.get_windows_volume_label(drive)
                    display_name = f"Ổ đĩa {volume_label} ({letter}:)" if volume_label else f"Ổ đĩa ({letter}:)"
                    paths[display_name] = drive

        elif platform.system() == "Linux":
            if os.path.isdir("/"): paths["Hệ thống (/)"] = "/"
            # Check common mount points for removable media
            mount_points = []
            try:
                with open('/proc/mounts', 'r') as f:
                    for line in f:
                        parts = line.split()
                        if len(parts) > 1:
                            mount_point = parts[1]
                            # Filter out common system/virtual filesystems and snap mounts
                            if mount_point.startswith(('/media/', '/run/media/', '/mnt')) and \
                               'tmpfs' not in parts[2] and 'squashfs' not in parts[2] and \
                               not mount_point.startswith('/snap'):
                                if os.path.exists(mount_point): # Check existence to avoid stale entries
                                    mount_points.append(mount_point)
            except FileNotFoundError:
                # Fallback for systems without /proc/mounts (less common)
                possible_media_parents = ["/media", f"/run/media/{os.getlogin()}", "/mnt"]
                for media_parent in possible_media_parents:
                     if os.path.isdir(media_parent):
                        try:
                            for item in os.listdir(media_parent):
                                p = os.path.join(media_parent, item)
                                if os.path.ismount(p) or (os.path.isdir(p) and not os.path.islink(p)):
                                     if p not in mount_points: mount_points.append(p)
                        except PermissionError:
                            print(f"Permission denied accessing {media_parent}")

            # Add unique mount points found
            for p in sorted(list(set(mount_points))):
                 item_name = os.path.basename(p)
                 paths[f"Thiết bị ({item_name})"] = p


        elif platform.system() == "Darwin": # macOS
             # User Applications
             user_apps = os.path.join(home, "Applications")
             if os.path.isdir(user_apps): paths["Ứng dụng (User)"] = user_apps
             # System Applications
             if os.path.isdir("/Applications"): paths["Ứng dụng (System)"] = "/Applications"
             # Volumes (Disks and Network Mounts)
             if os.path.isdir("/Volumes"):
                 try:
                     for vol in os.listdir("/Volumes"):
                         p = os.path.join("/Volumes", vol)
                         # Check if it's a directory, not a link, and not the primary boot volume (heuristic)
                         # and not the home directory itself if it somehow ended up mounted there
                         if os.path.isdir(p) and not os.path.islink(p) and vol != "Macintosh HD" and not p.startswith(home):
                             paths[f"Volume ({vol})"] = p
                 except PermissionError:
                    print("Permission denied accessing /Volumes")

        return paths

    def get_windows_volume_label(self, drive_path):
        """Helper to get volume label on Windows using ctypes."""
        if platform.system() != "Windows": return ""
        volume_label = ""
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            buf = ctypes.create_unicode_buffer(1024)
            if kernel32.GetVolumeInformationW(ctypes.c_wchar_p(drive_path), buf, ctypes.sizeof(buf), None, None, None, None, 0):
                 volume_label = buf.value
        except Exception as e:
            print(f"Could not get volume label for {drive_path}: {e}")
        return volume_label

    def is_drive_root(self, path):
        """
        Checks if a given path string represents the root of a drive or volume.

        Args:
            path (str): The path string to check.

        Returns:
            bool: True if the path is a drive/volume root, False otherwise.
        """
        if not path or not isinstance(path, str):
            return False # Handle invalid input

        try:
            # Normalize and get absolute path for consistent checking
            abs_path = os.path.abspath(path)

            # --- Windows Check ---
            if platform.system() == "Windows":
                # Check if it's like C:\, D:\ etc.
                # os.path.ismount() can also work, but this is explicit.
                # Ensure it's not just "C:" but "C:\"
                if len(abs_path) == 3 and abs_path[1:] == ":\\" and abs_path[0].isalpha():
                    return True
                # Handle UNC paths maybe? For now, just local drives.

            # --- Linux/macOS Check ---
            elif platform.system() in ["Linux", "Darwin"]:
                # Check if it's the absolute filesystem root "/"
                if abs_path == os.path.abspath(os.sep): # os.sep is usually "/"
                    return True

                # Check if it's a known mount point from quick access.
                # This helps identify volumes like /media/user/USBDRIVE or /Volumes/ExternalHD
                # Avoid calling this recursively if called from within get_quick_access_paths itself
                # (though this specific method isn't called there currently)
                try:
                    # Get the dictionary of quick access paths {display_name: actual_path}
                    quick_paths = self.get_quick_access_paths()
                    # Check if the absolute version of any quick access path matches our abs_path
                    for display_name, q_path in quick_paths.items():
                        # We are interested in items marked as drives/devices/volumes
                        if ("Ổ đĩa" in display_name or \
                            "Thiết bị" in display_name or \
                            "Volume" in display_name or \
                            "Hệ thống (/)" in display_name): # Include root just in case
                             # Compare absolute paths to handle potential relative paths in quick_paths
                             if os.path.isdir(q_path) and os.path.abspath(q_path) == abs_path:
                                  return True
                except Exception as e:
                     # Handle potential errors during get_quick_access_paths if called early
                     print(f"Warning: Error checking quick access paths in is_drive_root: {e}")

        except Exception as e:
            # Handle potential errors during path manipulation (e.g., invalid characters)
            print(f"Error in is_drive_root checking path '{path}': {e}")
            return False

        # If none of the conditions above were met
        return False


    # --- Xử lý sự kiện UI ---
    def on_quick_nav_select(self, event=None):
        selection = self.quick_nav_var.get()
        paths = self.get_quick_access_paths() # Re-fetch in case drives changed
        target_path = paths.get(selection)
        if target_path and os.path.isdir(target_path):
            self.populate_local_tree(target_path)
        self.quick_nav_combo.set("Truy cập nhanh") # Reset display text
        self.quick_nav_combo.selection_clear() # Clear visual selection

    def navigate_local_from_entry(self, event=None):
        path_input = self.local_path_var.get().strip()

        # Check if user typed "Máy tính" (case-insensitive)
        if path_input.lower() == "máy tính":
            self.populate_local_tree(None) # Show "My Computer" view
            return

        # Existing logic for directory paths
        if os.path.isdir(path_input):
            self.populate_local_tree(path_input)
        else:
            messagebox.showerror("Đường dẫn không hợp lệ", f"'{path_input}' không phải là một thư mục hợp lệ hoặc không tồn tại.", parent=self.root)
            # Reset entry to reflect the actual current view
            if self.current_local_path is None:
                 self.local_path_var.set("Máy tính")
            else:
                 self.local_path_var.set(self.current_local_path)

    def go_up_local(self):
        # Case 1: Currently in "My Computer" view (path is None) - Cannot go up
        if self.current_local_path is None:
            print("Already at 'My Computer' view.")
            return

        # Case 2: Currently in a directory path
        parent_path = os.path.dirname(self.current_local_path)

        # Check if going up leads back to the same path (e.g., root "/")
        if parent_path == self.current_local_path:
            print("Already at filesystem root.")
            # Optional: Go to "My Computer" view from filesystem root?
            # self.populate_local_tree(None)
            return

        # Check if the parent *is* a drive root
        if self.is_drive_root(self.current_local_path):
             # If currently viewing C:\, going "up" should show the drive list
             print(f"Going up from drive root '{self.current_local_path}' to 'My Computer'.")
             self.populate_local_tree(None) # Go to "My Computer" view
        elif os.path.isdir(parent_path):
             # Regular directory, go up normally
             print(f"Going up from '{self.current_local_path}' to '{parent_path}'.")
             self.populate_local_tree(parent_path)
        else:
            # Parent path isn't valid for some reason, maybe go to My Computer?
            print(f"Cannot determine valid parent for '{self.current_local_path}'. Going to 'My Computer'.")
            self.populate_local_tree(None)


    def on_theme_change(self, event=None):
        selected_theme = self.theme_combobox.get()
        self.settings["theme"] = selected_theme
        self.apply_settings() # Re-applies theme and other settings

    def on_font_size_change_live(self, value_str):
        size = int(float(value_str))
        self.font_size_display_var.set(size)
        # Only apply if changed to avoid rapid updates
        if self.settings["font_size"] != size:
            self.settings["font_size"] = size
            self.apply_settings()

    def toggle_token_visibility(self):
        current_content = self.api_token_entry.get()
        if self.show_token_var.get(): # If checked (wants to show)
            real_token = self.settings.get("api_token", "")
            self.api_token_entry.config(show="")
            # Update entry only if it's currently masked or empty
            if current_content == "*******" or not current_content:
                 self.api_token_entry.delete(0, tk.END)
                 self.api_token_entry.insert(0, real_token)
        else: # If unchecked (wants to hide)
            self.api_token_entry.config(show="*")
            real_token = self.settings.get("api_token", "")
            display_value = "*******" if real_token else ""
            # Update entry only if it's currently showing the real token or is different from mask
            if current_content == real_token or current_content != display_value:
                self.api_token_entry.delete(0, tk.END)
                self.api_token_entry.insert(0, display_value)

    def save_settings_ui(self):
        # Read UI elements and store in self.settings
        self.settings["theme"] = self.theme_combobox.get()
        self.settings["font_size"] = self.font_size_display_var.get()
        self.settings["show_icons"] = self.show_icons_var.get()

        # Handle API token carefully based on visibility
        entered_token = self.api_token_entry.get()
        if self.show_token_var.get(): # If token is visible, save what's entered
            self.settings["api_token"] = entered_token
        elif entered_token != "*******": # If hidden but changed from mask, save it
             self.settings["api_token"] = entered_token
        # If hidden and still '*******', don't change the saved token

        self.save_settings() # Persist settings to file
        self.apply_settings() # Apply the saved settings to the UI
        messagebox.showinfo("Đã lưu", "Cài đặt đã được lưu và áp dụng.")
        # Refresh token display based on current visibility state after save
        self.toggle_token_visibility()
        self.toggle_token_visibility() # Call twice to restore correct state

    def update_status(self, message, progress=None):
        self.status_var.set(message)
        if progress is not None:
            self.progress_bar['value'] = progress
            self.progress_bar.config(mode='determinate')
            if progress >= 100 or progress < 0: # Hide progress bar when done or idle
                 # Schedule hiding slightly later to ensure visibility during final update
                 self.root.after(1000, lambda: self.progress_bar.config(value=0))
        else:
            self.progress_bar['value'] = 0
            # self.progress_bar.pack_forget() # Alternative: hide completely
        self.root.update_idletasks()

    def process_queue(self):
        try:
            while True:
                task_id, message, progress, finished, data = update_queue.get_nowait()
                status_text = f"Task {task_id}: {message}" if task_id else message
                self.update_status(status_text, progress)

                if finished:
                    if task_id in self.upload_tasks:
                         self.upload_tasks[task_id]['status'] = message
                         self.upload_tasks[task_id]['progress'] = progress
                         print(f"Task {task_id} ({self.upload_tasks.get(task_id,{}).get('type','unknown')}) finished: {message}")
                         # Maybe remove finished task from dict?
                         # del self.upload_tasks[task_id]

                    # Refresh relevant view if requested by the finished task
                    if data and 'refresh_view' in data:
                        if data['refresh_view'] == 'local':
                            refresh_path = data.get('path', self.current_local_path)
                            # Check if the finished task operated on the currently viewed directory or its parent
                            if self.current_local_path is not None and refresh_path is not None and \
                                (os.path.normpath(self.current_local_path) == os.path.normpath(refresh_path) or
                                 os.path.normpath(self.current_local_path) == os.path.normpath(os.path.dirname(refresh_path))):
                                print(f"Refreshing local view due to task completion: {self.current_local_path}")
                                self.populate_local_tree(self.current_local_path)
                            elif self.current_local_path is None and refresh_path is not None:
                                # If we are in "My Computer" view, refresh if the target was a drive root
                                if self.is_drive_root(refresh_path):
                                     print("Refreshing 'My Computer' view due to task completion on drive.")
                                     self.populate_local_tree(None)
                        elif data['refresh_view'] == 'github':
                            # Check if the finished task operated on the currently viewed repo/path
                            task_repo = data.get('repo', None) # Task might provide context
                            current_repo = self.current_github_context.get('repo')
                            if task_repo is None or task_repo == current_repo: # Refresh if task context matches current view or is unknown
                                print(f"Refreshing GitHub view: {self.current_github_context}")
                                self.refresh_github_tree_current_view()

                update_queue.task_done()
        except queue.Empty:
            pass
        finally:
            # Schedule the next check
            self.root.after(150, self.process_queue)


    # --- Logic Local Explorer ---
    def populate_local_tree(self, path):
        # Clear existing items first
        for i in self.local_tree.get_children():
            self.local_tree.delete(i)

        # Reset sort indicators whenever view changes
        if hasattr(self, 'sort_reverse'):
            for col in self.local_tree['columns'] + ('#0',):
                try:
                    heading_options = self.local_tree.heading(col)
                    if heading_options and 'text' in heading_options:
                        current_text = heading_options['text']
                        self.local_tree.heading(col, text=current_text.replace(' ▲', '').replace(' ▼', ''))
                except tk.TclError: pass
            self.sort_reverse = {}

        show_icons = self.settings.get("show_icons", True)
        home_path = os.path.expanduser("~") # Needed for fallback

        # --- Handle "My Computer" View ---
        if path is None: # Signal to show drives list
            self.current_local_path = None # Indicate we are in "My Computer" view
            self.local_path_var.set("Máy tính") # Update path entry display
            self.update_status("Hiển thị danh sách ổ đĩa.")

            try:
                drives_data = []
                quick_paths = self.get_quick_access_paths()
                for display_name, drive_path in quick_paths.items():
                    # Filter for items that represent drives/volumes
                    if ("Ổ đĩa" in display_name or \
                        "Thiết bị" in display_name or \
                        "Volume" in display_name or \
                        "Hệ thống (/)" in display_name):
                        # Ensure the path is valid before adding
                        if os.path.isdir(drive_path):
                             drives_data.append({
                                 'display_name': display_name, # Already formatted name
                                 'path': drive_path
                             })

                if not drives_data:
                     # If no drives found (very unlikely), fallback to Home
                     print("Warning: No drives found for 'My Computer' view. Falling back to Home.")
                     self.populate_local_tree(home_path)
                     return

                # Sort drives by display name
                drives_data.sort(key=lambda x: x['display_name'])

                # Populate tree with drives
                for drive in drives_data:
                    icon_prefix = DRIVE_ICON + " " if show_icons else ""
                    display_text = f"{icon_prefix}{drive['display_name']}"
                    # Use the actual path as the item ID (iid)
                    self.local_tree.insert("", tk.END,
                                           text=display_text,
                                           values=("Ổ đĩa", "", ""), # Type, Size, Modified
                                           iid=drive['path'])
                return # IMPORTANT: Stop execution here for "My Computer" view

            except Exception as e:
                 print(f"Error populating 'My Computer' view: {e}. Falling back to Home.")
                 # Fallback to home directory if drive listing fails
                 self.populate_local_tree(home_path)
                 return
        # --- END CHANGE: Handle "My Computer" View ---

        # --- Existing Logic for Directory Paths ---
        # Check if the non-None path is a valid directory
        if not os.path.isdir(path):
            messagebox.showerror("Lỗi", f"Đường dẫn không hợp lệ hoặc không thể truy cập:\n{path}", parent=self.root)
            # Fallback logic: Try Home, then root
            if os.path.isdir(home_path):
                print(f"Invalid path '{path}', falling back to Home.")
                self.populate_local_tree(home_path)
            else:
                 # Absolute fallback if Home is also bad
                 print(f"Invalid path '{path}' and Home ('{home_path}') is invalid. Falling back to root.")
                 self.populate_local_tree(os.path.abspath(os.sep))
            return

        # If path is a valid directory, proceed with listing contents...
        self.current_local_path = os.path.abspath(path)
        self.local_path_var.set(self.current_local_path)
        self.update_status(f"Đang xem: {self.current_local_path}")

        items_data = []
        try:
            for item in os.listdir(path):
                full_path = os.path.join(path, item)
                icon_prefix = ""
                try:
                    is_link = os.path.islink(full_path)
                    is_dir = os.path.isdir(full_path)
                    is_file = os.path.isfile(full_path)
                    is_drive = self.is_drive_root(full_path) # Still useful here

                    if is_drive: # Should not happen often when inside another dir, but check
                         item_type = "Ổ đĩa"
                         if show_icons: icon_prefix = DRIVE_ICON + " "
                    elif is_dir and not is_link:
                         item_type = "Thư mục"
                         if show_icons: icon_prefix = FOLDER_ICON + " "
                    elif is_file and not is_link:
                         item_type = "Tập tin"
                         if show_icons: icon_prefix = FILE_ICON + " "
                    elif is_link:
                         item_type = "Liên kết"
                         if show_icons: icon_prefix = FILE_ICON + " "
                    else:
                         item_type = "Khác"
                         if show_icons: icon_prefix = FILE_ICON + " "

                    try:
                        stat_info = os.lstat(full_path) if is_link else os.stat(full_path)
                        size_bytes = stat_info.st_size
                        modified_time = stat_info.st_mtime
                    except OSError:
                        size_bytes = 0
                        modified_time = 0

                    if is_file and not is_link:
                        if size_bytes < 1024: item_size_str = f"{size_bytes} B"
                        elif size_bytes < 1024**2: item_size_str = f"{size_bytes/1024:.1f} KB"
                        elif size_bytes < 1024**3: item_size_str = f"{size_bytes/1024**2:.1f} MB"
                        else: item_size_str = f"{size_bytes/1024**3:.1f} GB"
                    else:
                        item_size_str = ""

                    if modified_time > 0:
                        try:
                            from datetime import datetime
                            dt_object = datetime.fromtimestamp(modified_time)
                            modified_str = dt_object.strftime("%Y-%m-%d %H:%M")
                        except Exception: modified_str = "N/A"
                    else: modified_str = "N/A"

                    items_data.append({
                        'name': item,
                        'display_text': f"{icon_prefix}{item}",
                        'type': item_type,
                        'size_str': item_size_str,
                        'modified_str': modified_str,
                        'full_path': full_path,
                        'is_dir': is_dir and not is_link,
                        'is_drive': is_drive,
                        'sort_name': item.lower()
                    })

                except OSError as e:
                    print(f"Skipping item due to access error: {full_path} - {e}")
                    continue

            # Sort: Drives first, then Dirs, then Files, then Links/Other, then alphabetically
            items_data.sort(key=lambda x: (x['type'] != "Ổ đĩa", x['type'] != "Thư mục", x['type'] != "Tập tin", x['type'] != "Liên kết", x['sort_name']))


            # Add ".." entry if not at a drive root or file system root
            if not self.is_drive_root(path) and os.path.dirname(path) != path:
                 parent_path = os.path.dirname(path)
                 self.local_tree.insert("", tk.END,
                                        text="..",
                                        values=("Parent Directory", "", ""),
                                        iid=parent_path) # Use parent path as iid for '..'


            # Add sorted items
            for item_data in items_data:
                 self.local_tree.insert("", tk.END,
                                       text=item_data['display_text'],
                                       values=(item_data['type'], item_data['size_str'], item_data['modified_str']),
                                       iid=item_data['full_path'])

        except FileNotFoundError:
            messagebox.showerror("Lỗi", f"Đường dẫn không tồn tại: {path}", parent=self.root)
            self.populate_local_tree(home_path) # Go home on error
        except PermissionError:
            messagebox.showerror("Lỗi", f"Không có quyền truy cập vào: {path}", parent=self.root)
            parent = os.path.dirname(path)
            if parent != path:
                 # Try going up, but if going up leads to a drive root, go to "My Computer"
                 if self.is_drive_root(parent):
                     self.populate_local_tree(None)
                 else:
                     self.populate_local_tree(parent)
            else:
                 self.populate_local_tree(None) # Go to My Computer if can't go up from root permission error


    def on_local_item_double_click(self, event):
        item_id = self.local_tree.focus() # Get the iid (full path)
        if not item_id: return

        # Handle '..' navigation
        if self.local_tree.item(item_id, 'text') == "..":
            self.go_up_local() # Use the existing go_up function
            return

        # Existing logic for files/dirs/links
        if os.path.isdir(item_id):
            if os.path.islink(item_id):
                 target_path = os.path.realpath(item_id)
                 if os.path.isdir(target_path):
                     self.populate_local_tree(target_path)
                 else:
                     messagebox.showinfo("Liên kết", f"Liên kết '{os.path.basename(item_id)}' trỏ đến:\n{target_path}\n(Không phải thư mục hợp lệ)")
            else: # It's a regular directory or a drive root (which is also a dir)
                self.populate_local_tree(item_id)
        elif os.path.isfile(item_id):
            try:
                print(f"Opening file: {item_id}")
                if platform.system() == "Windows":
                    os.startfile(item_id)
                elif platform.system() == "Darwin":
                    subprocess.call(('open', item_id))
                else: # Linux and other Unix-like
                    subprocess.call(('xdg-open', item_id))
            except FileNotFoundError:
                 messagebox.showerror("Lỗi mở file", f"Không tìm thấy lệnh để mở file. Hãy thử cài đặt 'xdg-utils' (Linux) hoặc kiểm tra cấu hình hệ thống.")
            except Exception as e:
                messagebox.showerror("Lỗi mở file", f"Không thể mở '{os.path.basename(item_id)}':\n{e}")
        elif os.path.islink(item_id):
             target_path = os.path.realpath(item_id) # Tries to resolve
             if not os.path.exists(target_path):
                  messagebox.showwarning("Liên kết hỏng", f"Liên kết '{os.path.basename(item_id)}' trỏ đến một vị trí không tồn tại:\n{target_path}")
             else:
                  messagebox.showinfo("Liên kết", f"Liên kết '{os.path.basename(item_id)}' trỏ đến:\n{target_path}")


    def get_selected_local_items(self):
        # --- START CHANGE: Filter out '..' item ---
        selected_ids = self.local_tree.selection()
        valid_selections = []
        for item_id in selected_ids:
            # Check if the item exists and its text is not ".."
            if self.local_tree.exists(item_id) and self.local_tree.item(item_id, 'text') != "..":
                valid_selections.append(item_id)
        return tuple(valid_selections)
        # --- END CHANGE ---


    # --- Logic GitHub Explorer ---
    def populate_github_tree(self, repo_name=None, path=""):
        # Clear existing items
        for i in self.github_tree.get_children():
            self.github_tree.delete(i)

        self.current_github_context = {'repo': repo_name, 'path': path}
        show_icons = self.settings.get("show_icons", True)

        # Reset sort indicators
        if hasattr(self, 'sort_reverse'):
            for col in self.github_tree['columns'] + ('#0',):
                 try:
                     heading_options = self.github_tree.heading(col)
                     if heading_options and 'text' in heading_options:
                         current_text = heading_options['text']
                         self.github_tree.heading(col, text=current_text.replace(' ▲', '').replace(' ▼', ''))
                 except tk.TclError: pass
            self.sort_reverse = {} # Clear sort state

        # Handle not authenticated state
        if not self.github_handler or not self.github_handler.is_authenticated():
            # iid must be unique and should not look like a real item id
            self.github_tree.insert("", tk.END, text="Vui lòng cấu hình API Token trong Cài đặt và thử lại.", iid="placeholder_no_auth")
            self.github_path_label_var.set("GitHub: Chưa xác thực")
            return

        # Update path label while loading
        self.github_path_label_var.set(f"GitHub: Đang tải...")
        self.root.update_idletasks() # Force UI update

        # --- Populate Repo List View ---
        if repo_name is None:
            self.github_path_label_var.set("GitHub: Danh sách Repositories")
            repos = self.github_handler.get_repos() # Handles errors internally
            if not repos:
                 # iid must be unique
                 self.github_tree.insert("", tk.END, text="Không thể tải danh sách repositories hoặc không có repo.", iid="placeholder_load_repo_fail")
                 return

            # Sort repos by name, case-insensitive
            repos.sort(key=lambda r: r.name.lower())

            for repo in repos:
                iid = f"repo_{repo.name}" # Unique ID for repo items
                display_text = f"{FOLDER_ICON} {repo.name}" if show_icons else repo.name
                # Insert repo item
                self.github_tree.insert("", tk.END,
                                       text=display_text,
                                       values=("Repository", "", repo.name), # Type, Size (empty), Hidden Path (repo name)
                                       iid=iid)

        # --- Populate Repo Content View ---
        else:
            # Construct display path
            current_display_path = f"{repo_name}/{path}".strip('/') if path else repo_name
            self.github_path_label_var.set(f"GitHub: {current_display_path}")

            # --- Add "Go Back" item ---
            parent_path = os.path.dirname(path).replace("\\", "/") if path else None
            if path: # If we are inside a directory within the repo
                parent_display_name = os.path.basename(parent_path) if parent_path else repo_name
                back_text = f".. (Lên '{parent_display_name}')"
                # IMPORTANT: Ensure back_iid does not contain '|' character if using that as separator later
                back_iid = f"back_{repo_name}_{parent_path if parent_path is not None else ''}".replace('|','_') # Replace '|' just in case
                back_values = ("", "", parent_path if parent_path is not None else "")
            else: # If we are at the root of the repo
                 back_text = ".. (Quay lại danh sách Repos)"
                 back_iid = "back_root"
                 back_values = ("", "", "")
            self.github_tree.insert("", tk.END, text=back_text, values=back_values, iid=back_iid)


            # --- Get and Populate Contents ---
            contents = self.github_handler.get_repo_contents(repo_name, path)

            # --- Refined Handling of Contents ---
            if contents is None:
                 if not path:
                     display_text = "(Repository này rỗng)"
                 else:
                     display_text = f"(Đường dẫn '{path}' không tồn tại)"
                 self.github_tree.insert("", tk.END, text=display_text, iid="placeholder_not_found_or_empty")
                 return

            elif isinstance(contents, list) and not contents:
                 self.github_tree.insert("", tk.END, text="(Thư mục rỗng)", iid="placeholder_empty_dir")
                 return

            elif isinstance(contents, list):
                contents.sort(key=lambda c: (c.type != 'dir', c.name.lower()))

                for item in contents:
                    item_type = "Thư mục" if item.type == "dir" else "Tập tin"
                    icon_prefix = ""
                    if show_icons:
                        icon_prefix = FOLDER_ICON + " " if item.type == "dir" else FILE_ICON + " "

                    item_size_str = ""
                    if item.type == "file":
                        size_bytes = item.size
                        if size_bytes < 1024: item_size_str = f"{size_bytes} B"
                        elif size_bytes < 1024**2: item_size_str = f"{size_bytes/1024:.1f} KB"
                        elif size_bytes < 1024**3: item_size_str = f"{size_bytes/1024**2:.1f} MB"
                        else: item_size_str = f"{size_bytes/1024**3:.1f} GB"

                    display_text = f"{icon_prefix}{item.name}"
                    # Use '|' as a safer separator for the iid components
                    # Replace any '|' in repo_name or path to avoid breaking the split later
                    safe_repo_name = repo_name.replace('|','_')
                    safe_path = item.path.replace('|','_')
                    safe_sha = item.sha.replace('|', '_') # SHA shouldn't have '|' but be safe
                    item_iid = f"gh_{item.type}_{safe_repo_name}|{safe_path}|{safe_sha}"

                    self.github_tree.insert("", tk.END, text=display_text,
                                           values=(item_type, item_size_str, item.path), # Keep original path in value
                                           iid=item_iid)

            else:
                print(f"Warning: Unexpected content type received from get_repo_contents: {type(contents)}")
                self.github_tree.insert("", tk.END, text="Lỗi không xác định khi tải nội dung.", iid="placeholder_load_content_fail")
                return

    def on_github_item_double_click(self, event):
        item_id = self.github_tree.focus()
        if not item_id: return

        # --- Handle "Go Back" items ---
        if item_id.startswith("back_"):
            if item_id == "back_root":
                 self.populate_github_tree() # Go back to repo list
            else:
                # Parse iid: back_repoName_parentPath (replace '|' with '_' during parse if needed)
                # Since we replaced '|' in repo name with '_', the structure might be complex.
                # A safer way is to retrieve the parent path from the item's values.
                try:
                    values = self.github_tree.item(item_id, 'values')
                    parent_path = values[2] # Assuming parent path is stored in the 3rd value slot
                    # Extract repo name from context as it's needed
                    current_repo = self.current_github_context.get('repo')
                    if current_repo:
                         self.populate_github_tree(repo_name=current_repo, path=parent_path)
                    else:
                         print("Error: Cannot go back, current repo context is lost.")
                         self.populate_github_tree() # Go to repo list as fallback
                except (IndexError, tk.TclError):
                    print(f"Error parsing 'back' item ID or values: {item_id}")
                    self.populate_github_tree() # Fallback to repo list
            return

        # --- Handle Repo items (from list view) ---
        elif item_id.startswith("repo_"):
            repo_name = item_id.split("_", 1)[1]
            self.populate_github_tree(repo_name=repo_name, path="") # Enter the repo root

        # --- Handle Directory items (from content view) ---
        elif item_id.startswith("gh_dir_"):
            info = self.get_info_from_gh_iid(item_id) # Use the parser
            if info:
                 self.populate_github_tree(repo_name=info['repo'], path=info['path'])
            else:
                 print(f"Error parsing GitHub directory item ID on double click: {item_id}")

        # --- Handle File items (optional: show info or attempt download?) ---
        elif item_id.startswith("gh_file_"):
             print(f"Double-clicked GitHub file: {self.github_tree.item(item_id, 'text')}")
             # Future: Add action like download or view info


    def get_info_from_gh_iid(self, item_id):
        """Helper to parse gh_ item IDs reliably using '|' as separator."""
        if not item_id.startswith("gh_"): return None
        try:
            # iid format: gh_{type}_{safe_repoName}|{safe_path}|{safe_sha}
            parts = item_id.split("|", 2)
            if len(parts) != 3:
                print(f"Error parsing ID '{item_id}': Incorrect number of '|' separators.")
                return None

            meta_parts = parts[0].split("_", 2)
            if len(meta_parts) != 3:
                print(f"Error parsing ID '{item_id}': Cannot split meta part '{parts[0]}' correctly.")
                return None

            item_type = meta_parts[1]
            # Repo name, path, sha were made safe by replacing '|' with '_'.
            # We don't need to reverse this for basic info retrieval,
            # but the *actual* path from the 'values' column is better for display/use.
            safe_repo_name = meta_parts[2] # Keep this one, it's likely correct
            safe_path = parts[1] # Use the safe path from the iid for consistency? Or get from value?
            sha = parts[2]

            # --- Get actual path and display name from Treeview item ---
            try:
                item_values = self.github_tree.item(item_id, 'values')
                actual_path = item_values[2] if len(item_values) > 2 else safe_path.replace('_', '|') # Fallback guess
            except tk.TclError:
                actual_path = safe_path.replace('_', '|') # Fallback if item vanished

            display_text = self.github_tree.item(item_id, 'text')
            name = ""
            if self.settings.get("show_icons"):
                 if display_text.startswith(FOLDER_ICON + " ") or display_text.startswith(FILE_ICON + " "):
                     name = display_text[2:]
                 else: name = display_text # Handles '..' or items without icons
            else: name = display_text

            return {
                 'id': item_id, 'repo': safe_repo_name, 'path': actual_path, # Return the potentially corrected path
                 'type': item_type, 'sha': sha, 'name': name
            }
        except (IndexError, tk.TclError) as e:
            print(f"Error parsing GitHub item ID '{item_id}': {e}")
            return None


    def get_selected_github_items_info(self):
        """Gets detailed info for selected GitHub items using the parser."""
        selected_ids = self.github_tree.selection()
        items_info = []
        for item_id in selected_ids:
            # --- Filter out placeholder/back items before parsing ---
            if item_id.startswith("placeholder_") or item_id.startswith("back_"):
                continue
            info = self.get_info_from_gh_iid(item_id)
            if info:
                items_info.append(info)
            elif item_id.startswith("repo_"): # Handle repo items from list view
                 repo_name = item_id.split("_", 1)[1]
                 items_info.append({
                     'id': item_id, 'repo': repo_name, 'path': '',
                     'type': 'repo', 'sha': None, 'name': repo_name # Simulate structure
                 })
        return items_info

    def refresh_github_tree_current_view(self):
        # Get current context and refresh
        repo = self.current_github_context.get('repo')
        path = self.current_github_context.get('path', "")
        print(f"Refreshing GitHub view: repo='{repo}', path='{path}'")
        # Clear selection before repopulating to avoid issues
        self.github_tree.selection_set([])
        self.populate_github_tree(repo, path)


    # --- Context Menus ---
    def show_local_context_menu(self, event):
        selection = self.local_tree.selection() # Get selected iids (paths)
        clicked_item_id = self.local_tree.identify_row(event.y) # Get iid under cursor
        context_menu = tk.Menu(self.root, tearoff=0)

        # Filter out '..' item from selection for actions
        valid_selection = self.get_selected_local_items()

        if valid_selection:
            num_selected = len(valid_selection)
            context_menu.add_command(label=f"Copy ({num_selected} mục)", command=self.copy_local_items)
            context_menu.add_command(label=f"Xóa ({num_selected} mục)", command=self.delete_selected_local_items)
            # Rename only possible for single selection and not a drive root or '..'
            if num_selected == 1:
                 item_id = valid_selection[0]
                 if not self.is_drive_root(item_id) and self.local_tree.item(item_id,'text') != "..":
                     context_menu.add_command(label="Đổi tên", command=self.rename_local_item)
            context_menu.add_separator()

        # Determine paste target directory
        paste_target_dir = self.current_local_path # Default target
        if clicked_item_id and self.local_tree.exists(clicked_item_id):
            item_text = self.local_tree.item(clicked_item_id, 'text')
            # Can paste *into* a directory, but not into '..' or files/drives
            if os.path.isdir(clicked_item_id) and item_text != "..":
                paste_target_dir = clicked_item_id
            elif self.current_local_path is None: # In "My Computer" view
                 paste_target_dir = None # Can't paste here

        # --- Paste from GitHub to Local ---
        if self.clipboard and self.clipboard.get('type') == 'remote' and paste_target_dir is not None:
             num_items = len(self.clipboard['items'])
             paste_dir_name = os.path.basename(paste_target_dir) if paste_target_dir else ""
             context_menu.add_command(
                 label=f"Paste ({num_items} mục GitHub) vào '{paste_dir_name}'",
                 command=lambda t=paste_target_dir: self.handle_paste_to_local(t)
             )
             context_menu.add_separator()

        # --- General Actions (only if not in 'My Computer' view) ---
        if self.current_local_path is not None:
             context_menu.add_command(label="Tạo thư mục mới", command=self.create_new_local_folder)
             context_menu.add_command(label="Làm mới", command=lambda: self.populate_local_tree(self.current_local_path))
        else:
            # Actions for 'My Computer' view (maybe just Refresh?)
             context_menu.add_command(label="Làm mới", command=lambda: self.populate_local_tree(None))


        # --- Show Menu ---
        if context_menu.index(tk.END) is not None:
            context_menu.tk_popup(event.x_root, event.y_root)


    # --- START CHANGE: Updated show_github_context_menu ---
    def show_github_context_menu(self, event):
        selection = self.github_tree.selection() # Get raw selected IDs
        clicked_item_id = self.github_tree.identify_row(event.y) # Get iid under cursor
        context_menu = tk.Menu(self.root, tearoff=0)

        # Determine paste target (repo/path)
        can_paste_here, paste_target_repo, paste_target_gh_path = self._determine_github_drop_target(self.github_tree, event.y)

        # --- Paste from Local to GitHub ---
        if self.clipboard and self.clipboard.get('type') == 'local' and can_paste_here:
            num_items = len(self.clipboard['items'])
            paste_location_display = f"{paste_target_repo}/{paste_target_gh_path}".strip('/') if paste_target_gh_path else paste_target_repo
            context_menu.add_command(
                label=f"Paste ({num_items} mục Local) vào '{paste_location_display}'",
                command=lambda repo=paste_target_repo, path=paste_target_gh_path: self.handle_paste_to_github(repo, path)
            )
            context_menu.add_separator()

        # --- Actions for Selected GitHub Items ---
        # Use get_selected_github_items_info which filters invalid items
        selection_info = self.get_selected_github_items_info()
        num_selected = len(selection_info)

        if num_selected > 0:
            # Add Copy (Prepare Download) command
            context_menu.add_command(label=f"Copy ({num_selected} mục GitHub)", command=self.copy_github_items)

            # --- Add Copy GitHub Link (only for single selection) ---
            if num_selected == 1:
                # Pass the single item's info (dict) or repo name (str)
                item_data_for_link = selection_info[0] # Contains full info including type='repo' if applicable
                context_menu.add_command(
                    label="Copy Link GitHub",
                    command=lambda data=item_data_for_link: self.copy_github_link_to_clipboard(data)
                )

            # Add Delete command
            context_menu.add_command(label=f"Xóa ({num_selected} mục)", command=self.delete_selected_github_items)
            # Add Download command (only if not selecting only repos)
            if any(item['type'] != 'repo' for item in selection_info):
                context_menu.add_command(label=f"Tải xuống ({num_selected} mục)", command=self.download_github_items)

            context_menu.add_separator()


        # --- General Actions (if authenticated) ---
        if self.github_handler and self.github_handler.is_authenticated():
             context_menu.add_command(label="Làm mới", command=self.refresh_github_tree_current_view)

        # --- Show Menu ---
        if context_menu.index(tk.END) is not None:
            context_menu.tk_popup(event.x_root, event.y_root)
    # --- END CHANGE: Updated show_github_context_menu ---

    # --- START CHANGE: Added copy_github_link_to_clipboard ---
    def copy_github_link_to_clipboard(self, item_data):
        """Copies the GitHub web URL for the selected item to the clipboard."""
        if not self.github_handler or not self.github_handler.is_authenticated() or not self.github_handler.user:
            self.update_status("Lỗi: Chưa xác thực GitHub để lấy link.")
            messagebox.showerror("Lỗi", "Chưa xác thực GitHub.")
            return

        try:
            user_login = self.github_handler.user.login
            repo_name = item_data['repo']
            item_type = item_data['type'] # 'file', 'dir', or 'repo'
            item_path = item_data.get('path', '') # Path is empty for repo type
            default_branch = "main" # Assuming 'main' as default branch for links
            url = None

            if not repo_name:
                 raise ValueError("Tên repository không hợp lệ.")

            if item_type == 'repo':
                # URL for the repository root
                url = f"https://github.com/{user_login}/{repo_name}"
            elif item_type == 'dir':
                # URL for a directory (tree view)
                url = f"https://github.com/{user_login}/{repo_name}/tree/{default_branch}/{item_path}"
            elif item_type == 'file':
                # URL for a file (blob view)
                url = f"https://github.com/{user_login}/{repo_name}/blob/{default_branch}/{item_path}"
            else:
                 self.update_status(f"Không thể tạo link cho loại item không xác định: {item_type}")
                 return

            # Clean up potential double slashes in URL path part if path was empty
            url = url.replace(f'/{default_branch}//', f'/{default_branch}/') # If path was ""
            url = url.replace(f'/{default_branch}/', f'/{default_branch}/') # Normalize just in case

            # Put on clipboard
            self.root.clipboard_clear()
            self.root.clipboard_append(url)
            self.update_status(f"Đã copy link vào clipboard: {url}")
            print(f"Copied URL: {url}")

        except Exception as e:
            self.update_status(f"Lỗi khi tạo link GitHub: {e}")
            messagebox.showerror("Lỗi Copy Link", f"Không thể tạo link GitHub:\n{e}", parent=self.root)
            print(f"Error generating GitHub link for {item_data}: {e}")
    # --- END CHANGE: Added copy_github_link_to_clipboard ---

    # --- Clipboard & Paste Handlers (Refactored for DnD reuse) ---

    def copy_local_items(self):
        selected_paths = self.get_selected_local_items() # Already filters '..'
        if selected_paths:
            self.clipboard = {
                'type': 'local',
                'items': [{'path': p, 'name': os.path.basename(p)} for p in selected_paths]
            }
            names = [item['name'] for item in self.clipboard['items']]
            self.update_status(f"Đã copy {len(names)} item cục bộ: {', '.join(names[:3])}{'...' if len(names) > 3 else ''}")
        else:
            self.clipboard = None
            self.update_status("Chưa chọn item cục bộ nào để copy.")

    def copy_github_items(self):
        selected_items_info = self.get_selected_github_items_info() # Already filters invalid, includes 'repo' type
        if selected_items_info:
            self.clipboard = {
                'type': 'remote',
                # Filter out 'repo' types before adding to clipboard for download/paste actions
                'items': [item for item in selected_items_info if item['type'] != 'repo']
            }
            if not self.clipboard['items']: # If only repos were selected
                 self.update_status("Chỉ có thể copy (tải xuống) file và thư mục, không phải repo.")
                 self.clipboard = None
                 return

            names = [item['name'] for item in self.clipboard['items']]
            self.update_status(f"Đã copy {len(names)} item GitHub (chuẩn bị tải): {', '.join(names[:3])}{'...' if len(names) > 3 else ''}")
        else:
            self.clipboard = None
            self.update_status("Chưa chọn item GitHub nào để copy (tải xuống).")


    def handle_paste_to_local(self, target_directory):
        """Handles pasting/dropping GitHub items to local. Uses clipboard."""
        if not self.clipboard or self.clipboard.get('type') != 'remote':
            self.update_status("Clipboard không chứa item GitHub hoặc rỗng.")
            return
        if not target_directory or not os.path.isdir(target_directory):
             messagebox.showerror("Lỗi", f"Thư mục đích không hợp lệ: {target_directory}")
             return
        # Use the shared initiation logic
        self._initiate_download(target_directory, self.clipboard['items'])
        self.clipboard = None # Clear clipboard after initiating paste/drop

    def handle_paste_to_github(self, target_repo, target_github_path):
        """Handles pasting/dropping local items to GitHub. Uses clipboard."""
        if not self.clipboard or self.clipboard.get('type') != 'local':
            self.update_status("Clipboard rỗng hoặc không chứa item cục bộ.")
            return
        if not target_repo:
             messagebox.showerror("Lỗi", "Không xác định được Repository đích.")
             return

        local_items = self.clipboard['items'] # List of {'path': ..., 'name': ...}
        # Use the shared initiation logic
        self._initiate_upload(target_repo, target_github_path, local_items)
        self.clipboard = None # Clear clipboard after initiating paste/drop

    # --- Core Upload/Download Initiation (called by paste and DnD) ---

    def _initiate_download(self, target_directory, github_items_info, is_dnd=False):
        """
        Handles overwrite checks and starts the download thread.
        github_items_info: list of dicts {repo, path, type, name, sha}
        is_dnd: flag to indicate if triggered by drag-drop
        """
        # Filter out any potential 'repo' type items that might have slipped through
        items_to_download = [item for item in github_items_info if item.get('type') != 'repo']

        if not items_to_download:
            self.update_status("Không có file hoặc thư mục GitHub nào được chọn để tải.")
            return
        if not target_directory or not os.path.isdir(target_directory):
             messagebox.showerror("Lỗi", f"Thư mục đích không hợp lệ: {target_directory}")
             return

        conflicts = []
        items_to_process_final = [] # Store dicts {'info': item_info, 'conflict': bool}
        for item in items_to_download:
            local_target_path = os.path.join(target_directory, item['name'])
            if os.path.exists(local_target_path):
                conflicts.append(item['name'])
                items_to_process_final.append({'info': item, 'conflict': True})
            else:
                items_to_process_final.append({'info': item, 'conflict': False})

        # --- Overwrite Confirmation Logic ---
        overwrite_all_confirmed = True # Assume yes unless conflicts require asking
        skip_conflicts = False
        if conflicts:
            conflict_list_str = "\n - ".join(conflicts[:5]) + ("\n - ..." if len(conflicts) > 5 else "")
            result = messagebox.askyesnocancel(
                "Xác nhận Ghi đè Cục bộ",
                f"Các file/thư mục sau đã tồn tại trong '{os.path.basename(target_directory)}':\n - {conflict_list_str}\n\n"
                "Yes: Ghi đè tất cả các mục bị trùng.\n"
                "No: Bỏ qua các mục bị trùng, chỉ tải các mục chưa có.\n"
                "Cancel: Hủy bỏ toàn bộ thao tác.",
                icon='warning',
                parent=self.root # Ensure dialog is on top
            )
            if result is None: # Cancel
                self.update_status("Đã hủy tải xuống.")
                return
            elif result is True: # Yes (Overwrite)
                overwrite_all_confirmed = True
                skip_conflicts = False
                # Keep all items in items_to_process_final
            else: # No (Skip)
                overwrite_all_confirmed = False # We won't overwrite
                skip_conflicts = True
                # Filter out conflicting items
                items_to_process_final = [item for item in items_to_process_final if not item['conflict']]
                if not items_to_process_final:
                     self.update_status("Đã hủy tải xuống (không có item mới để tải).")
                     return

        # Get the final list of item info dictionaries to process
        final_items_info_list = [item['info'] for item in items_to_process_final]
        if not final_items_info_list:
             self.update_status("Không có item nào để tải xuống.")
             return

        # Start the download thread with the final list and overwrite decision
        self.start_download_thread(target_directory, final_items_info_list, overwrite_all=overwrite_all_confirmed)


    def _initiate_upload(self, target_repo, target_github_path, local_items, is_dnd=False):
        """
        Handles overwrite checks (skipping if repo is empty) and starts the upload thread.
        local_items: list of dicts {'path': ..., 'name': ...}
        is_dnd: flag to indicate if triggered by drag-drop
        """
        if not self.github_handler or not self.github_handler.is_authenticated():
             messagebox.showerror("Lỗi", "Chưa kết nối GitHub.")
             return
        if not local_items:
            self.update_status("Không có item cục bộ nào được chọn/kéo thả.")
            return

        conflicts = []
        items_to_upload_final = [] # Store dicts {'path':..., 'name':..., 'conflict': bool}
        checking_failed = False
        is_repo_empty = False # Flag to track if repo is empty

        # Get repo object once
        try:
            gh_repo = self.github_handler.user.get_repo(target_repo)
        except GithubException as e:
             messagebox.showerror("Lỗi GitHub", f"Không thể truy cập repo '{target_repo}':\n{e.status} - {e.data.get('message', '')}")
             return
        except Exception as e:
             messagebox.showerror("Lỗi Kết nối", f"Lỗi khi truy cập repo '{target_repo}':\n{e}")
             return

        # Check if the target repository root is empty
        print(f"Checking if repo '{target_repo}' is empty before checking individual files...")
        self.update_status(f"Kiểm tra trạng thái repo '{target_repo}'...")
        try:
            # Use the handler method which returns None on 404 (empty or not found)
            root_contents = self.github_handler.get_repo_contents(target_repo, path="")
            if root_contents is None:
                is_repo_empty = True
                print(f"Repo '{target_repo}' appears to be empty. Skipping individual file conflict checks.")
                self.update_status(f"Repo '{target_repo}' trống, chuẩn bị upload...")
            else:
                 print(f"Repo '{target_repo}' is not empty. Proceeding with individual file checks.")
                 self.update_status("Đang kiểm tra file trùng trên GitHub...") # Status for non-empty repo check
        except Exception as e:
            messagebox.showerror("Lỗi Kiểm tra Repo", f"Không thể xác định trạng thái repo '{target_repo}':\n{e}")
            checking_failed = True
            is_repo_empty = False

        # Proceed only if initial repo check didn't fail
        if not checking_failed:
            # Loop through local items to check conflicts (only if repo is NOT empty)
            if not is_repo_empty:
                for item in local_items:
                    local_path = item['path']
                    item_name = item['name']
                    clean_target_path = target_github_path.strip('/')
                    gh_target_path_full = f"{clean_target_path}/{item_name}" if clean_target_path else item_name

                    if os.path.isfile(local_path):
                        try:
                            gh_repo.get_contents(gh_target_path_full)
                            conflicts.append(item_name)
                            items_to_upload_final.append({'path': local_path, 'name': item_name, 'conflict': True})
                            print(f"Conflict found: {gh_target_path_full}")
                        except UnknownObjectException:
                             items_to_upload_final.append({'path': local_path, 'name': item_name, 'conflict': False})
                             print(f"No conflict for: {gh_target_path_full}")
                        except GithubException as e:
                             if e.status == 404:
                                 items_to_upload_final.append({'path': local_path, 'name': item_name, 'conflict': False})
                                 print(f"No conflict for (404 GithubException): {gh_target_path_full}")
                             else:
                                 messagebox.showerror("Lỗi Kiểm tra GitHub", f"Không thể kiểm tra file '{item_name}' trên GitHub:\n{e.status} - {e.data.get('message', '')}")
                                 checking_failed = True; break
                        except Exception as e:
                             messagebox.showerror("Lỗi", f"Lỗi không xác định khi kiểm tra file '{item_name}':\n{e}")
                             checking_failed = True; break
                    elif os.path.isdir(local_path):
                         items_to_upload_final.append({'path': local_path, 'name': item_name, 'conflict': False})
                         print(f"Directory queued (no pre-check): {item_name}")

                    if checking_failed: break

            else: # If repo IS empty, assume no conflicts for all items
                for item in local_items:
                     items_to_upload_final.append({'path': item['path'], 'name': item['name'], 'conflict': False})

        # Overwrite Confirmation (only if checks ran and found conflicts)
        if not checking_failed:
             self.update_status("Kiểm tra hoàn tất.")

             overwrite_confirmed = True
             skip_conflicts = False
             if conflicts: # Only show dialog if conflicts were actually found
                 conflict_list_str = "\n - ".join(conflicts[:5]) + ("\n - ..." if len(conflicts) > 5 else "")
                 result = messagebox.askyesnocancel(
                     "Xác nhận Ghi đè GitHub",
                      f"Các file sau đã tồn tại trên GitHub tại đường dẫn đích:\n - {conflict_list_str}\n\n"
                     "Yes: Ghi đè tất cả file trùng.\n"
                     "No: Bỏ qua các file bị trùng, chỉ upload các file chưa có.\n"
                     "Cancel: Hủy bỏ toàn bộ thao tác.",
                     icon='warning',
                     parent=self.root
                 )
                 if result is None:
                     self.update_status("Đã hủy upload.")
                     return
                 elif result is True:
                     overwrite_confirmed = True
                     skip_conflicts = False
                 else: # No
                     overwrite_confirmed = False
                     skip_conflicts = True
                     items_to_upload_final = [item for item in items_to_upload_final if not (os.path.isfile(item['path']) and item['conflict'])]
                     if not items_to_upload_final:
                          self.update_status("Đã hủy upload (không có file mới hoặc thư mục để upload).")
                          return

             final_local_paths_list = [item['path'] for item in items_to_upload_final]
             if not final_local_paths_list:
                 self.update_status("Không có item nào để upload.")
                 return

             effective_overwrite = is_repo_empty or overwrite_confirmed
             self.start_upload_thread(target_repo, target_github_path, final_local_paths_list, overwrite=effective_overwrite)

        else: # Checking failed earlier
             self.update_status("Hủy upload do lỗi kiểm tra file hoặc trạng thái repo.")


    # --- Local Actions ---
    def delete_selected_local_items(self, event=None):
        selected_paths = self.get_selected_local_items() # Already filters '..'
        if not selected_paths:
            self.update_status("Chưa chọn item cục bộ nào để xóa.")
            return

        names = [os.path.basename(p) for p in selected_paths]
        confirm_msg = f"Bạn có chắc chắn muốn xóa vĩnh viễn {len(names)} item(s) sau đây khỏi máy tính không?\n\n"
        confirm_msg += "\n - ".join([f"'{name}'" for name in names[:10]])
        if len(names) > 10: confirm_msg += "\n - ..."
        confirm_msg += "\n\nHành động này KHÔNG THỂ hoàn tác và sẽ xóa cả nội dung thư mục!"

        if messagebox.askyesno("Xác nhận Xóa Cục bộ", confirm_msg, icon='warning', parent=self.root):
            deleted_count = 0
            errors = []
            for path in selected_paths:
                try:
                    item_name = os.path.basename(path) # For error messages
                    if os.path.isfile(path) or os.path.islink(path):
                        os.remove(path)
                        print(f"Deleted file/link: {path}")
                    elif os.path.isdir(path):
                        shutil.rmtree(path)
                        print(f"Deleted directory: {path}")
                    else:
                        print(f"Skipping unknown item type: {path}")
                        continue
                    deleted_count += 1
                except Exception as e:
                    error_msg = f"Lỗi khi xóa '{item_name}': {e}"
                    print(error_msg)
                    errors.append(error_msg)

            # Refresh the local tree view after deletion attempts
            refresh_path = self.current_local_path
            self.populate_local_tree(refresh_path)

            # Report result
            if not errors:
                self.update_status(f"Đã xóa thành công {deleted_count} item(s).")
            else:
                messagebox.showerror("Lỗi Xóa", f"Đã xóa {deleted_count} item(s) nhưng xảy ra lỗi với {len(errors)} mục:\n" + "\n".join(errors[:3]) + ("\n..." if len(errors) > 3 else ""), parent=self.root)
                self.update_status(f"Xóa hoàn tất với {len(errors)} lỗi.")

    def rename_local_item(self):
        selected_paths = self.get_selected_local_items() # Already filters '..'
        if len(selected_paths) != 1: return # Only rename one item
        old_path = selected_paths[0]
        old_name = os.path.basename(old_path)
        directory = os.path.dirname(old_path)

        if self.is_drive_root(old_path):
             messagebox.showwarning("Không thể đổi tên", "Không thể đổi tên gốc ổ đĩa/volume.", parent=self.root)
             return

        new_name = simpledialog.askstring("Đổi tên", f"Nhập tên mới cho '{old_name}':", initialvalue=old_name, parent=self.root)

        if new_name and new_name != old_name:
            new_path = os.path.join(directory, new_name)
            if os.path.exists(new_path):
                 messagebox.showerror("Lỗi Đổi Tên", f"Tên '{new_name}' đã tồn tại trong thư mục này.", parent=self.root)
                 return

            invalid_chars = '\\/:*?"<>|' if platform.system() == "Windows" else "/"
            if any(char in invalid_chars for char in new_name):
                 messagebox.showerror("Lỗi Đổi Tên", f"Tên file/thư mục không được chứa các ký tự: {invalid_chars}", parent=self.root)
                 return

            try:
                os.rename(old_path, new_path)
                self.update_status(f"Đã đổi tên '{old_name}' thành '{new_name}'.")
                self.populate_local_tree(directory)
                if self.local_tree.exists(new_path):
                     self.local_tree.selection_set(new_path)
                     self.local_tree.focus(new_path)
                     self.local_tree.see(new_path)

            except Exception as e:
                 messagebox.showerror("Lỗi Đổi Tên", f"Không thể đổi tên:\n{e}", parent=self.root)
                 self.update_status(f"Lỗi khi đổi tên '{old_name}'.")
        elif new_name == old_name:
             self.update_status("Tên không đổi.")
        else: # User cancelled
             self.update_status("Đã hủy đổi tên.")


    def create_new_local_folder(self):
        target_directory = self.current_local_path
        if target_directory is None: # Cannot create folder in "My Computer" view
             messagebox.showwarning("Hành động không hợp lệ", "Không thể tạo thư mục trong chế độ xem 'Máy tính'.", parent=self.root)
             return

        folder_name = simpledialog.askstring("Tạo Thư mục Mới", "Nhập tên cho thư mục mới:", parent=self.root)

        if folder_name: # User entered a name and didn't cancel
            new_folder_path = os.path.join(target_directory, folder_name)
            if os.path.exists(new_folder_path):
                 messagebox.showerror("Lỗi Tạo Thư mục", f"Thư mục '{folder_name}' đã tồn tại.", parent=self.root)
                 return

            invalid_chars = '\\/:*?"<>|' if platform.system() == "Windows" else "/"
            if any(char in invalid_chars for char in folder_name):
                 messagebox.showerror("Lỗi Tạo Thư mục", f"Tên thư mục không được chứa các ký tự: {invalid_chars}", parent=self.root)
                 return

            try:
                os.makedirs(new_folder_path)
                self.update_status(f"Đã tạo thư mục '{folder_name}'.")
                self.populate_local_tree(target_directory)
                if self.local_tree.exists(new_folder_path):
                     self.local_tree.selection_set(new_folder_path)
                     self.local_tree.focus(new_folder_path)
                     self.local_tree.see(new_folder_path)
            except Exception as e:
                 messagebox.showerror("Lỗi Tạo Thư mục", f"Không thể tạo thư mục:\n{e}", parent=self.root)
                 self.update_status(f"Lỗi khi tạo thư mục '{folder_name}'.")
        else: # User cancelled
             self.update_status("Đã hủy tạo thư mục.")

    # --- GITHUB Actions ---
    def delete_selected_github_items(self, event=None):
        selected_items = self.get_selected_github_items_info() # List of dicts (includes 'repo' type)
        # Filter out repo items, as they cannot be deleted this way
        items_to_delete = [item for item in selected_items if item.get('type') != 'repo']

        if not items_to_delete:
            self.update_status("Vui lòng chọn file hoặc thư mục trên GitHub để xóa.")
            return

        # Assume all items are from the same repo (UI enforces this view)
        repo_name = items_to_delete[0]['repo']

        # Separate files and directories for confirmation message
        files_to_delete = [item for item in items_to_delete if item['type'] == 'file']
        dirs_to_delete = [item for item in items_to_delete if item['type'] == 'dir']

        # Build confirmation message
        confirm_msg = f"Bạn có chắc chắn muốn xóa {len(items_to_delete)} mục sau khỏi GitHub Repo '{repo_name}' không?\n"
        if files_to_delete:
             confirm_msg += "\n--- FILE ---\n" + "\n".join([f" - '{item['name']}'" for item in files_to_delete[:5]])
             if len(files_to_delete) > 5: confirm_msg += "\n - ..."
        if dirs_to_delete:
             confirm_msg += "\n\n--- THƯ MỤC ---\n" + "\n".join([f" - '{item['name']}'" for item in dirs_to_delete[:5]])
             if len(dirs_to_delete) > 5: confirm_msg += "\n - ..."
             confirm_msg += "\n\n(LƯU Ý: Xóa thư mục chỉ thành công nếu thư mục đó RỖNG trên GitHub.)"

        confirm_msg += "\n\nHành động này KHÔNG THỂ hoàn tác!"

        # Ask for confirmation
        if messagebox.askyesno("Xác nhận Xóa GitHub", confirm_msg, icon='warning', parent=self.root):
            delete_count = 0
            # Start a delete thread for each selected file/directory
            for item in items_to_delete:
                 self.start_delete_thread(item['repo'], item['path'], item['sha'])
                 delete_count += 1
            self.update_status(f"Đã yêu cầu xóa {delete_count} mục trên GitHub...")


    def download_github_items(self, specific_items=None):
        """Initiates download via context menu or potentially direct call."""
        selected_items = specific_items if specific_items else self.get_selected_github_items_info()
        # Filter out 'repo' type items, cannot download a repo directly like this
        items_to_process = [item for item in selected_items if item.get('type') != 'repo']

        if not items_to_process:
            self.update_status("Vui lòng chọn file hoặc thư mục trên GitHub để tải xuống.")
            return

        # Ask user for target directory
        initial_dir_guess = self.current_local_path if self.current_local_path else os.path.expanduser("~")
        target_directory = filedialog.askdirectory(
            title=f"Chọn thư mục lưu cho {len(items_to_process)} mục",
            initialdir=initial_dir_guess,
            parent=self.root
        )

        if not target_directory:
            self.update_status("Đã hủy tải xuống.")
            return

        # Use the shared initiation logic (handles overwrite checks)
        self._initiate_download(target_directory, items_to_process)


    # --- Drag and Drop Implementation ---
    def setup_drag_drop(self):
        # Bind to ButtonPress to initiate potential drag
        self.local_tree.bind("<ButtonPress-1>", self.on_dnd_press)
        self.github_tree.bind("<ButtonPress-1>", self.on_dnd_press)

        # Bind to Motion while Button1 is held down
        self.local_tree.bind("<B1-Motion>", self.on_dnd_motion)
        self.github_tree.bind("<B1-Motion>", self.on_dnd_motion)

        # Bind to ButtonRelease to finalize or cancel drag
        self.local_tree.bind("<ButtonRelease-1>", self.on_dnd_release)
        self.github_tree.bind("<ButtonRelease-1>", self.on_dnd_release)


    def on_dnd_press(self, event):
        widget = event.widget
        row_id = widget.identify_row(event.y)
        # Only start if clicking on a valid item row (and not the '..' item)
        if row_id and widget.exists(row_id):
            item_text = widget.item(row_id, 'text')
            # Prevent dragging '..' or placeholder items
            if item_text == ".." or row_id.startswith("placeholder_") or row_id.startswith("back_"):
                print(f"DnD Press: Ignoring non-draggable item: {item_text}")
                self._dnd_source_widget = None
                self._dnd_items = None
                self._dnd_dragging = False
                return

            self._dnd_dragging = False # Not dragging *yet*
            self._dnd_start_x = event.x
            self._dnd_start_y = event.y
            self._dnd_source_widget = widget
            self._dnd_items = None # Clear previous drag data
            print(f"DnD Press: Source={widget.winfo_class()}, RowID={row_id}")
        else:
            # Clicked on empty space, reset potential drag state
            self._dnd_source_widget = None
            self._dnd_items = None
            self._dnd_dragging = False
            print("DnD Press: Clicked empty space, ignoring.")


    def on_dnd_motion(self, event):
        # Check if a potential drag was initiated and button is still held
        if self._dnd_source_widget is None or not (event.state & 0x0100):
            return # No valid drag start or button released

        # If already dragging, maybe update cursor or provide visual feedback
        if self._dnd_dragging:
            return

        # --- Check threshold to start the actual drag ---
        dx = abs(event.x - self._dnd_start_x)
        dy = abs(event.y - self._dnd_start_y)
        threshold = 5 # Pixels movement needed

        if dx > threshold or dy > threshold:
            print(f"--- DnD Motion: Threshold Exceeded (dx={dx}, dy={dy}), attempting drag start ---")
            potential_items = None
            items_list = []

            # --- Get items from the source widget ---
            if self._dnd_source_widget == self.local_tree:
                selected_paths = self.get_selected_local_items() # Filters '..'
                print(f"DnD Motion: Getting local items: {selected_paths}")
                if selected_paths:
                    items_list = [{'path': p, 'name': os.path.basename(p)} for p in selected_paths]
                    if items_list:
                         potential_items = {'type': 'local', 'items': items_list}

            elif self._dnd_source_widget == self.github_tree:
                selected_items_info = self.get_selected_github_items_info() # Filters placeholders/back
                # Filter out 'repo' type items for dragging actions (upload/download)
                items_list = [info for info in selected_items_info if info['type'] != 'repo']
                print(f"DnD Motion: Getting GitHub items: {len(items_list)} valid items (files/dirs)")
                if items_list:
                    potential_items = {'type': 'remote', 'items': items_list}

            # --- Finalize drag start if items were acquired ---
            if potential_items and potential_items['items']:
                self._dnd_items = potential_items
                self._dnd_dragging = True # <<< NOW we are officially dragging
                print(f"--- DnD Motion: Drag Confirmed! Type: {self._dnd_items['type']}, Items: {[item['name'] for item in self._dnd_items['items']]} ---")
                # Optional: Change cursor
                # self.root.config(cursor="hand2")
            else:
                print("--- DnD Motion: Threshold Exceeded, but no valid draggable items selected/found. Drag NOT started. ---")
                self._dnd_source_widget = None # <<< Prevent further motion checks for this press
                self._dnd_dragging = False
                self._dnd_items = None


    def on_dnd_release(self, event):
        print(f"DnD Release: Dragging={self._dnd_dragging}, Source={self._dnd_source_widget}, Items={self._dnd_items is not None}")
        # Optional: Reset global cursor if changed
        # self.root.config(cursor="")

        target_widget = self.root.winfo_containing(event.x_root, event.y_root) # Find widget under cursor
        # Refine target_widget if it's not one of the trees
        temp_widget = target_widget
        while temp_widget is not None:
             if isinstance(temp_widget, ttk.Treeview):
                 target_widget = temp_widget # Found the actual tree
                 break
             temp_widget = temp_widget.master
        print(f"DnD Release: Target Widget under cursor: {target_widget.winfo_class() if target_widget else 'None'}")


        # --- Check if a valid drag was in progress ---
        if not self._dnd_dragging or not self._dnd_items or self._dnd_source_widget is None:
             print("DnD Release: No valid drag operation was active.")
             self._dnd_dragging = False
             self._dnd_items = None
             self._dnd_source_widget = None
             return

        # --- A valid drag was released ---
        source_widget = self._dnd_source_widget
        dragged_data = self._dnd_items # Contains {'type': 'local'/'remote', 'items': [...]}

        # --- Case 1: Dropped Local onto GitHub Tree ---
        if source_widget == self.local_tree and target_widget == self.github_tree:
            print("DnD Release: Detected drop Local -> GitHub Tree")
            # Determine the specific target within the GitHub tree
            can_drop, target_repo, target_gh_path = self._determine_github_drop_target(target_widget, event.y)
            if can_drop:
                print(f"DnD Release: Valid GitHub drop target: Repo='{target_repo}', Path='{target_gh_path}'")
                self.update_status(f"Thả {len(dragged_data['items'])} mục vào {target_repo}/{target_gh_path}...")
                # Initiate upload using the determined target
                self._initiate_upload(target_repo, target_gh_path, dragged_data['items'], is_dnd=True)
            else:
                self.update_status("Hủy thả: Không thể thả vào vị trí GitHub này.")
                print("DnD Release: Invalid GitHub drop target.")

         # --- Case 2: Dropped GitHub onto Local Tree ---
        elif source_widget == self.github_tree and target_widget == self.local_tree:
            print("DnD Release: Detected drop GitHub -> Local Tree")
            # Determine the specific target within the Local tree
            can_drop, target_local_dir = self._determine_local_drop_target(target_widget, event.y)
            if can_drop:
                print(f"DnD Release: Valid Local drop target: Dir='{target_local_dir}'")
                self.update_status(f"Thả {len(dragged_data['items'])} mục vào {os.path.basename(target_local_dir)}...")
                # Initiate download using the determined target
                self._initiate_download(target_local_dir, dragged_data['items'], is_dnd=True)
            else:
                self.update_status("Hủy thả: Không thể thả vào vị trí cục bộ này.")
                print("DnD Release: Invalid Local drop target.")

        # --- Case 3: Dropped onto self or other widget (Ignore) ---
        else:
            if source_widget == target_widget:
                 print(f"DnD Release: Drop ignored (dropped onto source: {source_widget.winfo_class()}).")
            else:
                 print(f"DnD Release: Drop ignored (dropped onto invalid widget: {target_widget.winfo_class() if target_widget else 'None'}).")
            self.update_status("Hủy thả.")

        # --- Cleanup Drag State ---
        print("DnD Release: Cleaning up drag state.")
        self._dnd_dragging = False
        self._dnd_items = None
        self._dnd_source_widget = None
        # Optional: Reset widget cursors if they were changed


    def _determine_local_drop_target(self, tree_widget, event_y):
        """Determines the target local directory for a drop. Returns (can_drop, target_path)."""
        item_id = tree_widget.identify_row(event_y) # Get iid (path) under cursor
        if item_id and tree_widget.exists(item_id):
            item_text = tree_widget.item(item_id, 'text')
            # Dropped onto an existing item
            if os.path.isdir(item_id) and item_text != "..":
                # Make sure it's not a link pretending to be a dir for drop target
                if not os.path.islink(item_id):
                    print(f"Local Drop Target: Directory '{item_id}'")
                    return True, item_id # Drop into this directory
                else:
                    print(f"Local Drop Target: Link '{item_id}' - Invalid")
                    return False, None # Cannot drop onto a link currently
            else:
                # Dropped onto a file, drive root, or '..' (cannot drop *into* these)
                 print(f"Local Drop Target: Invalid item '{item_text}' ({item_id})")
                 return False, None
        else:
            # Dropped onto empty space - use current directory (if not 'My Computer')
            if self.current_local_path is not None:
                print(f"Local Drop Target: Empty space, using current dir '{self.current_local_path}'")
                return True, self.current_local_path
            else:
                print("Local Drop Target: Empty space in 'My Computer' view - Invalid")
                return False, None # Cannot drop into 'My Computer' view

    def _determine_github_drop_target(self, tree_widget, event_y):
        """Determines the target repo/path for a GitHub drop. Returns (can_drop, repo, path)."""
        item_id = tree_widget.identify_row(event_y) # Get iid under cursor

        if item_id and tree_widget.exists(item_id):
            # Case 1: Dropped onto a repo in the root list view
            if item_id.startswith("repo_"):
                repo_name = item_id.split("_", 1)[1]
                print(f"GitHub Drop Target: Repo Root '{repo_name}'")
                return True, repo_name, "" # Drop into repo root

            # Case 2: Dropped onto a directory inside a repo content view
            elif item_id.startswith("gh_dir_"):
                info = self.get_info_from_gh_iid(item_id)
                if info:
                     print(f"GitHub Drop Target: Directory '{info['repo']}/{info['path']}'")
                     return True, info['repo'], info['path'] # Drop into this GitHub directory
                else:
                     print(f"GitHub Drop Target: Error parsing gh_dir iid '{item_id}'")
                     return False, None, None # Error parsing

            # Case 3: Dropped onto a file, 'back' item, or placeholder - invalid drop target
            else:
                 item_text = tree_widget.item(item_id, 'text')
                 print(f"GitHub Drop Target: Invalid item '{item_text}' ({item_id})")
                 return False, None, None
        else:
            # Case 4: Dropped onto empty space
            # Allow drop only if currently viewing contents of a repo
            current_repo = self.current_github_context.get('repo')
            if current_repo:
                current_path = self.current_github_context.get('path', "")
                print(f"GitHub Drop Target: Empty space in repo view '{current_repo}/{current_path}'")
                return True, current_repo, current_path
            else:
                # Dropped into empty space in the main repo list - invalid
                print("GitHub Drop Target: Empty space in repo list view - Invalid")
                return False, None, None


    # --- Threading for background tasks ---

    # UPLOAD Thread
    def start_upload_thread(self, repo_name, github_path, local_paths, overwrite):
        if not self.github_handler or not self.github_handler.is_authenticated():
            messagebox.showerror("Lỗi", "Chưa kết nối GitHub.")
            return
        self.task_id_counter += 1
        task_id = self.task_id_counter
        thread = threading.Thread(target=self._upload_worker,
                                  args=(task_id, repo_name, github_path, local_paths, overwrite),
                                  daemon=True)
        self.upload_tasks[task_id] = {'thread': thread, 'status': 'Bắt đầu...', 'progress': 0, 'type': 'upload', 'repo': repo_name}
        base_display = f"{repo_name}/{github_path}".strip('/') if github_path else repo_name
        self.update_status(f"Task {task_id}: Bắt đầu upload {len(local_paths)} item(s) tới '{base_display}'...", 0)
        thread.start()

    def _upload_worker(self, task_id, repo_name, github_path_base, local_paths_initial, overwrite):
        total_items_estimated = 0 # Start at 0, count as we go
        processed_count = 0; success_count = 0; errors = []; skipped_count = 0

        upload_queue = queue.Queue()
        # Initial population and count
        for local_path in local_paths_initial:
             upload_queue.put((local_path, github_path_base))
             if os.path.isfile(local_path): total_items_estimated += 1
             elif os.path.isdir(local_path): total_items_estimated += 1 # Count dir itself initially

        while not upload_queue.empty():
            local_item_path, current_gh_target_dir = upload_queue.get()
            item_name = os.path.basename(local_item_path)

            # Determine relative path for display messages
            relative_display_path = item_name
            try:
                 # Find base directory of the initial drag/paste set
                 common_base = os.path.commonpath(local_paths_initial)
                 # If the common path is a directory containing all items, use its parent
                 if all(local_item_path.startswith(os.path.join(common_base, '')) for local_item_path in local_paths_initial) and os.path.isdir(common_base):
                      display_base = os.path.dirname(common_base)
                 else: # Otherwise, use the parent of the first item (less precise but works for single items)
                      display_base = os.path.dirname(local_paths_initial[0])

                 relative_display_path = os.path.relpath(local_item_path, display_base)
            except (ValueError, IndexError):
                 relative_display_path = item_name # Fallback

            # Calculate progress
            current_progress = int((processed_count / total_items_estimated) * 95) if total_items_estimated > 0 else 0
            update_queue.put((task_id, f"Xử lý: {relative_display_path}", current_progress, False, None))

            if os.path.isfile(local_item_path):
                processed_count += 1 # Increment before potential blocking call
                update_queue.put((task_id, f"Đang upload: {relative_display_path}", current_progress, False, None))
                success, message = self.github_handler.upload_file(
                    repo_name, local_item_path, current_gh_target_dir,
                    commit_message=f"Upload {relative_display_path} via app",
                    overwrite=overwrite
                )

                if success:
                    success_count += 1; msg = f"OK: {relative_display_path}"
                elif message == "exists":
                    skipped_count += 1; msg = f"Bỏ qua (trùng): {relative_display_path}"
                else:
                    msg = f"LỖI upload {relative_display_path}: {message}"
                    errors.append(f"Upload error '{relative_display_path}': {message}")

                final_file_progress = int((processed_count / total_items_estimated) * 95) if total_items_estimated > 0 else 0
                update_queue.put((task_id, msg, final_file_progress, False, None))

            elif os.path.isdir(local_item_path):
                processed_count += 1 # Count dir as processed when we start scanning it
                clean_current_gh_target_dir = current_gh_target_dir.strip('/')
                new_gh_dir_for_contents = f"{clean_current_gh_target_dir}/{item_name}" if clean_current_gh_target_dir else item_name

                try:
                    sub_items = os.listdir(local_item_path)
                    if not sub_items:
                        print(f"Directory is empty, skipping contents: {local_item_path}")
                        update_queue.put((task_id, f"OK (Thư mục rỗng): {relative_display_path}", current_progress, False, None))
                        success_count += 1 # Count empty dir as success
                    else:
                        update_queue.put((task_id, f"Quét thư mục: {relative_display_path}", current_progress, False, None))
                        new_items_found_in_dir = 0
                        for sub_item_name in sub_items:
                            sub_local_path = os.path.join(local_item_path, sub_item_name)
                            upload_queue.put((sub_local_path, new_gh_dir_for_contents))
                            # Increment estimate only if it's a file or non-empty dir? More complex. Just count all.
                            new_items_found_in_dir += 1
                        total_items_estimated += new_items_found_in_dir # Update total estimate
                        print(f"Added {new_items_found_in_dir} items from '{item_name}' to queue. New total estimate: {total_items_estimated}")
                        success_count += 1 # Count the directory itself as a "success" once children are queued

                except PermissionError as e:
                    msg_err = f"LỖI đọc thư mục cục bộ {relative_display_path}: {e}";
                    update_queue.put((task_id, msg_err, current_progress, False, None));
                    errors.append(f"Dir read error '{relative_display_path}': {e}")
                except Exception as e:
                     msg_err = f"LỖI xử lý thư mục {relative_display_path}: {e}";
                     update_queue.put((task_id, msg_err, current_progress, False, None));
                     errors.append(f"Dir processing error '{relative_display_path}': {e}")

            else: # Skip sockets, links, etc.
                processed_count += 1 # Count as processed/skipped
                update_queue.put((task_id, f"Bỏ qua (loại không hỗ trợ): {relative_display_path}", current_progress, False, None));
                skipped_count += 1

            upload_queue.task_done() # Mark item from queue as processed

        # --- Final Report ---
        base_display = f"{repo_name}/{github_path_base}".strip('/') if github_path_base else repo_name
        final_message = f"Hoàn thành upload tới '{base_display}'. {success_count} thành công."
        if skipped_count > 0: final_message += f" {skipped_count} bỏ qua."
        if errors: final_message += f" Có {len(errors)} lỗi."; print(f"--- Task {task_id} Upload Errors ---:\n" + "\n".join(errors) + "\n------------------------------")

        refresh_data = {'refresh_view': 'github', 'repo': repo_name}
        update_queue.put((task_id, final_message, 100, True, refresh_data))


    # DELETE Thread
    def start_delete_thread(self, repo_name, github_path, sha):
        if not self.github_handler or not self.github_handler.is_authenticated():
            messagebox.showerror("Lỗi", "Chưa kết nối GitHub.")
            return
        self.task_id_counter += 1
        task_id = self.task_id_counter
        thread = threading.Thread(target=self._delete_worker, args=(task_id, repo_name, github_path, sha), daemon=True)
        self.upload_tasks[task_id] = {'thread': thread, 'status': 'Bắt đầu...', 'progress': 0, 'type': 'delete', 'repo': repo_name}
        item_name = os.path.basename(github_path) or github_path
        self.update_status(f"Task {task_id}: Bắt đầu xóa '{item_name}' từ '{repo_name}'...", 0)
        thread.start()

    def _delete_worker(self, task_id, repo_name, github_path, sha):
        item_name = os.path.basename(github_path) or github_path
        update_queue.put((task_id, f"Đang xóa: {item_name}...", 50, False, None))

        success, result_message = self.github_handler.delete_item(repo_name, github_path, sha)

        refresh_data = {'refresh_view': 'github', 'repo': repo_name} if success else None
        update_queue.put((task_id, result_message, 100, True, refresh_data))


    # DOWNLOAD Thread
    def start_download_thread(self, target_directory, items_to_download, overwrite_all):
        if not self.github_handler or not self.github_handler.is_authenticated():
            messagebox.showerror("Lỗi", "Chưa kết nối GitHub.")
            return
        self.task_id_counter += 1
        task_id = self.task_id_counter
        thread = threading.Thread(target=self._download_worker, args=(task_id, target_directory, items_to_download, overwrite_all), daemon=True)
        self.upload_tasks[task_id] = {'thread': thread, 'status': 'Bắt đầu...', 'progress': 0, 'type': 'download', 'path': target_directory}
        self.update_status(f"Task {task_id}: Bắt đầu tải xuống {len(items_to_download)} item(s) vào '{os.path.basename(target_directory)}'...", 0)
        thread.start()

    def _download_worker(self, task_id, target_directory_base, items_to_download_initial, overwrite_all):
        total_items_estimated = 0 # Count as we go
        processed_count = 0; success_count = 0; errors = []; skipped_overwrite = 0

        try:
             gh = self.github_handler.g; user = self.github_handler.user
             if not gh or not user: raise Exception("GitHub handler not authenticated.")
        except Exception as e:
             update_queue.put((task_id, f"Lỗi nghiêm trọng: {e}", 0, True, None)); return

        download_queue = queue.Queue()
        # Initial population and count
        for item_info in items_to_download_initial:
             download_queue.put((item_info, target_directory_base))
             total_items_estimated += 1 # Count initial items

        while not download_queue.empty():
            item_info, current_local_target_dir = download_queue.get()
            item_name = item_info['name']; item_type = item_info['type']
            repo_name = item_info['repo']; github_path = item_info['path']

            local_target_path = os.path.join(current_local_target_dir, item_name)

            # Determine relative path for display messages
            relative_display_path = item_name
            try:
                 relative_display_path = os.path.relpath(local_target_path, target_directory_base)
            except ValueError: pass # Fallback

            # Calculate progress
            current_progress = int((processed_count / total_items_estimated) * 95) if total_items_estimated > 0 else 0
            update_queue.put((task_id, f"Xử lý: {relative_display_path}", current_progress, False, None))

            # --- Check for local conflicts ---
            if os.path.exists(local_target_path):
                if not overwrite_all:
                    msg_skip = f"Bỏ qua (trùng): {relative_display_path}";
                    update_queue.put((task_id, msg_skip, current_progress, False, None));
                    skipped_overwrite += 1
                    processed_count += 1 # Increment count for the skipped item
                    download_queue.task_done(); continue
                else:
                    update_queue.put((task_id, f"Xóa file cũ: {relative_display_path}", current_progress, False, None))
                    try:
                         if os.path.isfile(local_target_path) or os.path.islink(local_target_path): os.remove(local_target_path)
                         elif os.path.isdir(local_target_path): shutil.rmtree(local_target_path)
                         print(f"Removed existing local item: {local_target_path}")
                    except Exception as e:
                         msg_err = f"LỖI xóa file/thư mục cục bộ cũ '{relative_display_path}': {e}"
                         update_queue.put((task_id, msg_err, current_progress, False, None)); errors.append(msg_err)
                         processed_count += 1
                         download_queue.task_done(); continue

            # --- Process Download ---
            processed_count += 1 # Increment count before potential blocking call
            try:
                # Get repo object (could cache)
                repo = user.get_repo(repo_name)

                if item_type == 'file':
                    update_queue.put((task_id, f"Đang tải file: {relative_display_path}...", current_progress, False, None))
                    os.makedirs(os.path.dirname(local_target_path), exist_ok=True)
                    file_content = repo.get_contents(github_path)
                    with open(local_target_path, "wb") as f:
                        if file_content.encoding == "base64" and isinstance(file_content.content, str):
                            import base64
                            f.write(base64.b64decode(file_content.content))
                        elif file_content.decoded_content:
                            f.write(file_content.decoded_content)
                        else:
                            raise ValueError(f"Could not get decoded content for {github_path}")
                    success_count += 1
                    msg_done = f"OK: {relative_display_path}";
                    update_queue.put((task_id, msg_done, current_progress, False, None))

                elif item_type == 'dir':
                    update_queue.put((task_id, f"Quét thư mục GH: {relative_display_path}...", current_progress, False, None))
                    os.makedirs(local_target_path, exist_ok=True)
                    contents = repo.get_contents(github_path)
                    if contents:
                         update_queue.put((task_id, f"Thêm {len(contents)} mục con từ: {relative_display_path}", current_progress, False, None))
                         new_items_found_in_dir = 0
                         for content_item in contents:
                              sub_item_info = {
                                  'repo': repo_name, 'path': content_item.path, 'type': content_item.type,
                                  'name': content_item.name, 'sha': content_item.sha
                              }
                              download_queue.put((sub_item_info, local_target_path))
                              new_items_found_in_dir += 1
                         total_items_estimated += new_items_found_in_dir # Update total estimate
                         print(f"Added {new_items_found_in_dir} sub-items from '{item_name}'. New estimate: {total_items_estimated}")
                         success_count += 1 # Count dir as success when children queued
                    else: # Empty directory on GitHub
                         print(f"Directory '{relative_display_path}' is empty on GitHub.")
                         msg_done = f"OK (Thư mục rỗng): {relative_display_path}";
                         update_queue.put((task_id, msg_done, current_progress, False, None))
                         success_count += 1

            except GithubException as e:
                 msg_err = f"LỖI GitHub tải '{relative_display_path}': {e.status} - {e.data.get('message','(No message)')}"
                 update_queue.put((task_id, msg_err, current_progress, False, None)); errors.append(msg_err)
            except Exception as e:
                 msg_err = f"LỖI tải xuống '{relative_display_path}': {e}"
                 update_queue.put((task_id, msg_err, current_progress, False, None)); errors.append(msg_err)

            download_queue.task_done() # Mark item from queue as processed

        # --- Final Report ---
        final_message = f"Hoàn thành tải xuống vào '{os.path.basename(target_directory_base)}'. {success_count} thành công."
        if skipped_overwrite > 0: final_message += f" {skipped_overwrite} bỏ qua (trùng)."
        if errors: final_message += f" Có {len(errors)} lỗi."; print(f"--- Task {task_id} Download Errors ---:\n" + "\n".join(errors) + "\n-------------------------------")

        # Request local view refresh for the base directory where download started
        refresh_data = {'refresh_view': 'local', 'path': target_directory_base}
        update_queue.put((task_id, final_message, 100, True, refresh_data))


# --- Chạy ứng dụng ---
if __name__ == "__main__":
    def load_initial_settings():
        try:
            with open(SETTINGS_FILE, 'r') as f:
                loaded = json.load(f)
                s = DEFAULT_SETTINGS.copy()
                s.update(loaded)
                return s
        except (FileNotFoundError, json.JSONDecodeError):
            return DEFAULT_SETTINGS.copy()

    initial_settings = load_initial_settings()
    initial_theme = initial_settings.get("theme", DEFAULT_SETTINGS["theme"])

    try:
        root = tb.Window(themename=initial_theme)
    except tk.TclError:
         print(f"Theme '{initial_theme}' not found at startup, using fallback '{DEFAULT_SETTINGS['theme']}'.")
         initial_theme = DEFAULT_SETTINGS["theme"]
         initial_settings["theme"] = initial_theme
         root = tb.Window(themename=initial_theme)

    root.title("GitHub Repository Manager")
    root.minsize(900, 600)
    root.geometry("1200x850")

    app = GitHubManagerApp(root)
    root.mainloop()

