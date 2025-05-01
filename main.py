# --- START OF REFACTORED FILE main.py (Reverting to 2-pane) ---

import tkinter as tk
from tkinter import ttk, messagebox, filedialog, font as tkFont, simpledialog, scrolledtext
import ttkbootstrap as tb
from ttkbootstrap.constants import *
import os
import shutil
import json
import threading
import queue
import time
from github import Github, GithubException, UnknownObjectException, RateLimitExceededException
import platform # Để lấy thông tin OS cho đường dẫn
import string   # Cho ký tự ổ đĩa Windows
import subprocess # Để mở file và lấy icon sau này (nếu cần)
import sys
import re

# --- Cài đặt và Cấu hình ---
SETTINGS_FILE = "app_settings.json"
DEFAULT_SETTINGS = {
    "theme": "litera",
    "font_size": 12,
    "api_token": "",
    "show_icons": True,
    "default_download_dir": os.path.expanduser("~")
}

# Hàng đợi giao tiếp GUI-Worker
update_queue = queue.Queue()

# --- Simple Icon Placeholders ---
FOLDER_ICON = "📁"
FILE_ICON = "📄"
DRIVE_ICON = "💽" # Icon ổ đĩa
REPO_ICON = "📦" # Icon repo GitHub

# --- Lớp xử lý GitHub API ---
class GitHubHandler:
    # ... (Giữ nguyên toàn bộ lớp GitHubHandler đã sửa lỗi trước đó) ...
    # Đảm bảo hàm get_repo_contents xử lý ref=None đúng cách
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
            except RateLimitExceededException:
                error_msg = "Lỗi GitHub: Đã vượt quá giới hạn Rate Limit API. Vui lòng thử lại sau hoặc sử dụng token xác thực."
                print(error_msg)
                # Avoid messagebox during init, log is sufficient
                # messagebox.showerror("Rate Limit", error_msg)
                self.g = None; self.user = None
            except GithubException as e:
                error_msg = f"Lỗi xác thực GitHub ({e.status}): {e.data.get('message', 'Unknown Error')}"
                print(error_msg)
                self.g = None; self.user = None
            except Exception as e:
                error_msg = f"Lỗi kết nối GitHub không mong muốn: {e}"
                print(error_msg)
                self.g = None; self.user = None

    def get_active_token(self):
        return self.authenticated_token

    def is_authenticated(self):
         return self.g is not None and self.user is not None and self.authenticated_token is not None

    def get_repos(self):
        if not self.is_authenticated(): return []
        try:
            repos = self.user.get_repos(type='all', sort='updated', direction='desc')
            repo_list = list(repos)
            print(f"Fetched {len(repo_list)} repositories.")
            return repo_list
        except RateLimitExceededException:
            messagebox.showerror("Rate Limit", "Vượt quá giới hạn API khi lấy danh sách repo.")
            return []
        except GithubException as e:
            messagebox.showerror("Lỗi lấy Repos", f"Không thể lấy danh sách repositories:\n{e.status} - {e.data.get('message', '')}")
            return []
        except Exception as e:
            messagebox.showerror("Lỗi không xác định", f"Đã xảy ra lỗi khi lấy danh sách repo:\n{e}")
            return []

    def get_repo_contents(self, repo_name, path="", ref=None):
        """Lấy nội dung repo, chỉ truyền ref khi có giá trị."""
        if not self.is_authenticated():
            return None # Trả về None nếu chưa xác thực

        try:
            repo = self.user.get_repo(repo_name)

            # ----- Gọi API chính - Chỉ truyền ref nếu nó không phải None -----
            if ref:
                print(f"Debug: Calling get_contents for '{repo_name}/{path}' with ref='{ref}'")
                contents = repo.get_contents(path, ref=ref)
            else:
                print(f"Debug: Calling get_contents for '{repo_name}/{path}' without ref (using default branch)")
                contents = repo.get_contents(path)
            # ----- Kết thúc gọi API -----

            # ----- Xử lý kết quả -----
            if contents is not None and not isinstance(contents, list):
                contents = [contents]
            return contents if contents else []

        except UnknownObjectException:
            print(f"Info: Path '{path}' in repo '{repo_name}' not found or empty (UnknownObjectException 404).")
            return []

        except GithubException as e:
            if e.status == 404:
                print(f"Info: Path '{path}' in repo '{repo_name}' not found or empty (GithubException 404).")
                return []
            elif e.status == 403 and e.data and "too large" in e.data.get('message', '').lower():
                print(f"Warning: Cannot list contents of '{path}' in '{repo_name}', directory too large.")
                messagebox.showwarning("Thư mục quá lớn", f"Không thể liệt kê nội dung của thư mục '{path}'.\nNó chứa quá nhiều mục.")
                return None
            elif isinstance(e, RateLimitExceededException):
                 print(f"!!! Rate Limit Exceeded when getting contents for '{repo_name}/{path}'")
                 messagebox.showerror("Rate Limit", f"Vượt quá giới hạn API khi lấy nội dung '{repo_name}/{path}'.")
                 return None
            else:
                print(f"!!! GitHub Error in get_repo_contents (GithubException): Status={e.status}, Data={e.data}")
                messagebox.showerror("Lỗi GitHub", f"Không thể lấy nội dung repo '{repo_name}' tại path '{path}'.\nLỗi: {e.status} - {e.data.get('message', 'Unknown Error')}")
                return None

        except Exception as e:
            import traceback
            print("!!! UNEXPECTED Error in get_repo_contents (Exception):")
            traceback.print_exc()
            messagebox.showerror("Lỗi không xác định", f"Đã xảy ra lỗi không mong muốn khi lấy nội dung repo:\n{type(e).__name__}: {e}")
            return None
    # ... (Các hàm khác của GitHubHandler: get_item_info, get_repo_info, delete_item, delete_repo, rename_repo, upload_file, rename_file) ...
    # Đảm bảo các hàm này không bị thiếu

    def get_item_info(self, repo_name, path):
        """Gets detailed info for a specific file or directory."""
        if not self.is_authenticated(): return None, "Chưa xác thực"
        try:
            repo = self.user.get_repo(repo_name)
            item = repo.get_contents(path)
            return item, None # Return ContentFile/list and no error
        except UnknownObjectException:
            return None, f"Không tìm thấy item tại '{path}'."
        except RateLimitExceededException:
             return None, "Vượt quá giới hạn Rate Limit API."
        except GithubException as e:
             return None, f"Lỗi GitHub ({e.status}): {e.data.get('message', 'Unknown Error')}"
        except Exception as e:
             return None, f"Lỗi không xác định: {e}"

    def get_repo_info(self, repo_name):
        """Gets detailed info for a specific repository."""
        if not self.is_authenticated(): return None, "Chưa xác thực"
        try:
            repo = self.user.get_repo(repo_name)
            return repo, None # Return Repository object and no error
        except UnknownObjectException:
            return None, f"Không tìm thấy repository '{repo_name}'."
        except RateLimitExceededException:
             return None, "Vượt quá giới hạn Rate Limit API."
        except GithubException as e:
             return None, f"Lỗi GitHub ({e.status}): {e.data.get('message', 'Unknown Error')}"
        except Exception as e:
             return None, f"Lỗi không xác định: {e}"

    def delete_item(self, repo_name, path, sha, commit_message="Delete item via app"):
        if not self.is_authenticated(): return False, "Chưa xác thực GitHub"
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
            elif e.status == 422 and "sha mismatch" in msg.lower():
                 return False, f"Lỗi: Item '{path}' đã bị thay đổi trên GitHub. Vui lòng làm mới và thử lại."
            else:
                return False, f"Lỗi GitHub khi xóa '{path}': {e.status} - {msg}"
        except RateLimitExceededException:
             return False, "Vượt quá giới hạn Rate Limit API khi xóa."
        except Exception as e:
            return False, f"Lỗi không xác định khi xóa '{path}':\n{e}"

    def delete_repo(self, repo_name):
        if not self.is_authenticated(): return False, "Chưa xác thực GitHub"
        try:
            repo = self.user.get_repo(repo_name)
            repo.delete()
            return True, f"Đã xóa thành công repository: {repo_name}"
        except UnknownObjectException:
            return False, f"Lỗi: Repository '{repo_name}' không tìm thấy."
        except RateLimitExceededException:
             return False, "Vượt quá giới hạn Rate Limit API khi xóa repo."
        except GithubException as e:
             msg = e.data.get('message', f'Lỗi GitHub khi xóa repo {repo_name}')
             return False, f"Lỗi GitHub khi xóa repo '{repo_name}': {e.status} - {msg}"
        except Exception as e:
             return False, f"Lỗi không xác định khi xóa repo '{repo_name}':\n{e}"

    def rename_repo(self, repo_name, new_name):
        if not self.is_authenticated(): return False, "Chưa xác thực GitHub"
        try:
            repo = self.user.get_repo(repo_name)
            repo.edit(name=new_name)
            return True, f"Đã đổi tên repo thành công thành: {new_name}"
        except UnknownObjectException:
            return False, f"Lỗi: Repository '{repo_name}' không tìm thấy."
        except RateLimitExceededException:
             return False, "Vượt quá giới hạn Rate Limit API khi đổi tên repo."
        except GithubException as e:
             msg = e.data.get('message', f'Lỗi GitHub khi đổi tên repo {repo_name}')
             err_details = e.data.get('errors', [])
             if err_details: msg += f" ({err_details[0].get('message', '')})"
             return False, f"Lỗi GitHub khi đổi tên repo '{repo_name}' thành '{new_name}': {e.status} - {msg}"
        except Exception as e:
             return False, f"Lỗi không xác định khi đổi tên repo '{repo_name}':\n{e}"

    def upload_file(self, repo_name, local_path, github_path, commit_message="Upload file via app", progress_callback=None, overwrite=False):
        # ... (Giữ nguyên hàm upload_file đã sửa lỗi trước đó) ...
        if not self.is_authenticated(): return False, "Chưa xác thực GitHub"
        try:
            repo = self.user.get_repo(repo_name)
            file_name = os.path.basename(local_path)
            clean_github_path = github_path.strip('/')
            target_path = f"{clean_github_path}/{file_name}" if clean_github_path else file_name

            existing_file_sha = None
            try:
                existing_file = repo.get_contents(target_path)
                if existing_file and not isinstance(existing_file, list):
                    existing_file_sha = existing_file.sha
                    print(f"Info: File '{target_path}' exists (SHA: {existing_file_sha}).")
                elif existing_file and isinstance(existing_file, list):
                    return False, f"Lỗi: Tên '{file_name}' đã tồn tại dưới dạng thư mục tại '{clean_github_path}'."
            except UnknownObjectException: print(f"Info: File '{target_path}' not found. Will create.")
            except GithubException as e:
                if e.status == 404: print(f"Info: File '{target_path}' not found (GithubException 404). Will create.")
                else: raise e
            except RateLimitExceededException: raise
            except Exception as e: raise

            try:
                with open(local_path, "rb") as f: content_bytes = f.read()
            except FileNotFoundError: return False, f"Lỗi: Không tìm thấy file cục bộ '{local_path}'"
            except Exception as e: return False, f"Lỗi đọc file cục bộ '{local_path}': {e}"

            status_msg = ""; action_description = ""
            try:
                if existing_file_sha:
                    action_description = "update"
                    if overwrite:
                        print(f"Action: Updating existing file: {target_path}")
                        repo.update_file(target_path, commit_message, content_bytes, existing_file_sha)
                        status_msg = f"Đã cập nhật file: {target_path}"
                    else:
                        print(f"Action: Skipping existing file (overwrite=False): {target_path}")
                        return False, "exists"
                else:
                    action_description = "create"
                    print(f"Action: Creating new file: {target_path}")
                    repo.create_file(target_path, commit_message, content_bytes)
                    status_msg = f"Đã upload file mới: {target_path}"

                if progress_callback: progress_callback(100)
                return True, status_msg

            except GithubException as e:
                 msg = e.data.get('message', f'Unknown GitHub Error during {action_description}')
                 if e.status == 422 and 'sha mismatch' in msg.lower() and action_description == 'update':
                     return False, f"Lỗi: File '{target_path}' đã bị thay đổi trên GitHub kể từ khi kiểm tra. Vui lòng làm mới và thử lại."
                 elif e.status == 409 and 'empty directories' in msg.lower():
                     return False, f"Lỗi: Xung đột với đánh dấu thư mục rỗng tại '{target_path}'."
                 else:
                     print(f"Error: GitHub {action_description} failed for '{target_path}': {e.status} - {msg}")
                     return False, f"Lỗi GitHub khi {action_description} file '{target_path}': {e.status} - {msg}"
            except RateLimitExceededException: raise
            except Exception as e:
                 print(f"Error: Unexpected error during {action_description} for '{target_path}': {e}")
                 return False, f"Lỗi không xác định khi {action_description} file '{target_path}':\n{e}"

        except RateLimitExceededException: return False, "Vượt quá giới hạn Rate Limit API."
        except GithubException as e:
             msg = e.data.get('message', 'Unknown GitHub Error during setup')
             print(f"Error: GitHub setup error for upload to '{repo_name}': {e.status} - {msg}")
             return False, f"Lỗi GitHub (setup): {e.status} - {msg}"
        except Exception as e:
             print(f"Error: Generic error during upload setup to '{repo_name}': {e}")
             return False, f"Lỗi không xác định (setup): {e}"

    def rename_file(self, repo_name, old_path, new_path, sha):
        """ Placeholder: Logic will be in the worker thread. """
        if not self.is_authenticated(): return False, "Chưa xác thực"
        print(f"Rename Prep: Repo='{repo_name}', Old='{old_path}', New='{new_path}', SHA='{sha}'")
        return True, "Yêu cầu đổi tên đã được gửi tới worker."

# --- Lớp ứng dụng chính ---
class GitHubManagerApp:

    def __init__(self, root):
        self.root = root
        print("Initializing GitHubManagerApp...")
        self.previous_settings = {}
        self.settings = self.load_settings()
        print(f"Settings loaded: {self.settings}")

        print("Initializing GitHubHandler...")
        self.github_handler = GitHubHandler(self.get_token())
        if self.github_handler.is_authenticated(): print(f"GitHub Handler authenticated as: {self.github_handler.user.login}")
        else: print("GitHub Handler not authenticated.")

        # Khởi tạo đường dẫn cục bộ ban đầu (Ví dụ: Máy tính hoặc Desktop)
        self.current_local_path = self._get_initial_local_path()
        print(f"Initial local path: {self.current_local_path}")

        self.clipboard = None # Khởi tạo clipboard
        self.upload_tasks = {}
        self.task_id_counter = 0
        self.current_github_context = {'repo': None, 'path': ""}

        print("Setting up styles...")
        self.setup_styles()

        print("Creating widgets...")
        self.create_widgets()

        print("Applying settings to UI elements...")
        self.apply_settings(force_refresh=True)

        # --- Populate Initial Views ---
        print("Populating initial Local tree view...")
        self.populate_local_tree(self.current_local_path)
        print("Populating initial GitHub tree view...")
        self.populate_github_tree()

        print("Starting background task queue processor...")
        self.process_queue()

        print("--- GitHubManagerApp initialized successfully. ---")
        self.log_status("Ứng dụng đã sẵn sàng.", "INFO")
        if not self.github_handler.is_authenticated():
            self.log_status("Chưa xác thực GitHub. Vui lòng vào Cài đặt.", "WARNING")

    # --- Helper lấy đường dẫn cục bộ ban đầu ---
    def _get_initial_local_path(self):
        """Xác định đường dẫn cục bộ ban đầu, ưu tiên Desktop."""
        try:
            desktop_path = None
            quick_paths = self.get_quick_access_paths() # Cần hàm này được định nghĩa trước
            desktop_path = quick_paths.get("Màn hình nền") # Giả sử key là 'Màn hình nền'

            if desktop_path and os.path.isdir(desktop_path):
                print(f"Defaulting initial local view to Desktop: {desktop_path}")
                return os.path.abspath(desktop_path)
            else:
                print("Desktop path not found or invalid. Defaulting to 'My Computer' view.")
                return None # None đại diện cho "My Computer"
        except Exception as e:
            print(f"Error determining Desktop path: {e}. Defaulting to 'My Computer' view.")
            return None

    # --- Cài đặt & Style ---
    def load_settings(self):
        # ... (Giữ nguyên hàm load_settings) ...
        try:
            with open(SETTINGS_FILE, 'r') as f:
                loaded_settings = json.load(f)
                final_settings = DEFAULT_SETTINGS.copy()
                final_settings.update(loaded_settings)
                if "default_download_dir" not in final_settings or not os.path.isdir(final_settings["default_download_dir"]):
                     final_settings["default_download_dir"] = os.path.expanduser("~")
                return final_settings
        except (FileNotFoundError, json.JSONDecodeError):
            s = DEFAULT_SETTINGS.copy()
            s["default_download_dir"] = os.path.expanduser("~")
            return s
        except Exception as e:
            print(f"Error loading settings: {e}. Using defaults.")
            s = DEFAULT_SETTINGS.copy()
            s["default_download_dir"] = os.path.expanduser("~")
            return s

    def save_settings(self):
        # ... (Giữ nguyên hàm save_settings) ...
        try:
            with open(SETTINGS_FILE, 'w') as f:
                json.dump(self.settings, f, indent=4)
            print(f"Settings saved to {SETTINGS_FILE}")
            self.log_status("Đã lưu cài đặt.", "SUCCESS") # Log success
        except Exception as e:
            self.log_status(f"Lỗi lưu cài đặt: {e}", "ERROR") # Log error
            messagebox.showerror("Lỗi Lưu Cài Đặt", f"Không thể lưu file cài đặt:\n{e}")

    def get_token(self):
        return self.settings.get("api_token", "")

    def setup_styles(self):
        # ... (Giữ nguyên hàm setup_styles) ...
        self.style = tb.Style()
        initial_theme = self.settings.get("theme", DEFAULT_SETTINGS["theme"])
        try:
            if initial_theme not in self.style.theme_names():
                 print(f"Warning: Initial theme '{initial_theme}' not found, using fallback.")
                 initial_theme = DEFAULT_SETTINGS["theme"]; self.settings["theme"] = initial_theme
            self.style.theme_use(initial_theme)
            print(f"Theme '{initial_theme}' applied successfully.")
        except tk.TclError as e:
             print(f"Error applying initial theme '{initial_theme}': {e}. Using fallback.")
             try:
                  fallback_theme = DEFAULT_SETTINGS["theme"]; self.style.theme_use(fallback_theme); self.settings["theme"] = fallback_theme
                  print(f"Fallback theme '{fallback_theme}' applied.")
             except tk.TclError as e_fallback: print(f"FATAL: Could not apply default theme: {e_fallback}")
        except Exception as e: print(f"Unexpected error setting up style: {e}")

        self.default_font = tkFont.nametofont("TkDefaultFont")
        self.update_font_size()

    def update_font_size(self):
        # --- SỬA ĐỔI: Áp dụng font cho cả hai Treeview ---
        size = self.settings.get("font_size", 10)
        try:
            self.default_font.configure(size=size)
            row_height = int(size * 2.2) if size >= 10 else 22
            # Áp dụng cho cả hai treeview
            self.style.configure("Treeview", font=(self.default_font.actual("family"), size), rowheight=row_height)
            # Adjust other widgets
            self.style.configure("TLabel", font=(self.default_font.actual("family"), size))
            self.style.configure("TButton", font=(self.default_font.actual("family"), size))
            self.style.configure("TEntry", font=(self.default_font.actual("family"), size))
            self.style.configure("TCombobox", font=(self.default_font.actual("family"), size))
            self.style.configure("TCheckbutton", font=(self.default_font.actual("family"), size))
            self.style.configure("TLabelframe.Label", font=(self.default_font.actual("family"), size))
            self.style.configure("Status.TLabel", font=(self.default_font.actual("family"), max(8, size-2)))

            if hasattr(self, 'status_log_area'):
                log_font_family = self.default_font.actual("family")
                log_font_size = max(8, size - 1)
                self.status_log_area.config(font=(log_font_family, log_font_size))

            # Cấu hình lại style cho các treeview nếu chúng đã tồn tại
            if hasattr(self, 'local_tree'): self.local_tree.configure(style="Treeview")
            if hasattr(self, 'github_tree'): self.github_tree.configure(style="Treeview")

        except tk.TclError as e: print(f"Error applying font size {size}: {e}")
        except Exception as e: print(f"Unexpected error updating font size: {e}")


    def apply_settings(self, force_refresh=False):
        # --- SỬA ĐỔI: Refresh cả hai Treeview nếu cần ---
        self.previous_settings = self.settings.copy()
        # --- Apply Theme ---
        selected_theme = self.settings.get("theme", DEFAULT_SETTINGS["theme"])
        try:
            current_theme = self.style.theme_use()
            if selected_theme != current_theme:
                if selected_theme not in self.style.theme_names():
                    print(f"Warning: Theme '{selected_theme}' not found, falling back.")
                    selected_theme = DEFAULT_SETTINGS["theme"]; self.settings["theme"] = selected_theme
                self.style.theme_use(selected_theme)
                print(f"Theme changed to '{selected_theme}'.")
                # Update log colors on theme change
                self.status_log_area.tag_config("INFO", foreground=self.style.colors.info)
                self.status_log_area.tag_config("SUCCESS", foreground=self.style.colors.success)
                self.status_log_area.tag_config("WARNING", foreground=self.style.colors.warning)
                self.status_log_area.tag_config("ERROR", foreground=self.style.colors.danger)
                self.status_log_area.tag_config("MUTED", foreground=self.style.colors.secondary)
        except tk.TclError as e: print(f"Error applying theme '{selected_theme}': {e}.")
        except Exception as e: print(f"Unexpected error applying theme: {e}")

        # --- Apply Font Size ---
        self.update_font_size()

        # --- Update Settings UI Elements ---
        if hasattr(self, 'theme_combobox') and self.theme_combobox.winfo_exists():
             current_theme = self.settings.get("theme", DEFAULT_SETTINGS["theme"])
             self.theme_combobox.set(current_theme if current_theme in self.theme_combobox['values'] else DEFAULT_SETTINGS["theme"])
        if hasattr(self, 'font_size_scale') and self.font_size_scale.winfo_exists():
            self.font_size_scale.set(self.settings.get("font_size", DEFAULT_SETTINGS["font_size"]))
            self.font_size_display_var.set(self.settings.get("font_size", DEFAULT_SETTINGS["font_size"]))
        if hasattr(self, 'api_token_entry') and self.api_token_entry.winfo_exists():
            current_token = self.get_token(); display_value = "*******" if current_token else ""
            try:
                if self.api_token_entry.get() != display_value and self.api_token_entry['show'] == '*':
                    is_focused = self.root.focus_get() == self.api_token_entry
                    if not is_focused: self.api_token_entry.delete(0, tk.END); self.api_token_entry.insert(0, display_value)
                    elif not self.api_token_entry.get() and display_value: self.api_token_entry.delete(0, tk.END); self.api_token_entry.insert(0, display_value)
            except tk.TclError as e: print(f"Error updating api_token_entry widget: {e}")
        if hasattr(self, 'show_icons_checkbutton') and self.show_icons_checkbutton.winfo_exists():
             self.show_icons_var.set(self.settings.get("show_icons", DEFAULT_SETTINGS["show_icons"]))
        if hasattr(self, 'default_download_entry') and self.default_download_entry.winfo_exists():
             self.default_download_dir_var.set(self.settings.get("default_download_dir", os.path.expanduser("~")))

        # --- Check for changes requiring refresh ---
        refresh_needed = force_refresh or \
                         self.settings.get("show_icons") != self.previous_settings.get("show_icons")

        # --- Apply GitHub Token & Re-initialize Handler ---
        token_from_settings = self.get_token(); needs_reinit = False
        if not hasattr(self, 'github_handler') or self.github_handler is None: needs_reinit = bool(token_from_settings)
        elif not self.github_handler.is_authenticated() and token_from_settings: needs_reinit = True
        elif self.github_handler.is_authenticated() and self.github_handler.get_active_token() != token_from_settings: needs_reinit = True
        elif self.github_handler.is_authenticated() and not token_from_settings: needs_reinit = True # Token removed

        if needs_reinit:
            print("Applying settings: Re-initializing GitHub Handler...")
            self.github_handler = GitHubHandler(token_from_settings)
            refresh_needed = True # Luôn refresh GitHub tree sau khi xác thực lại

        # --- Perform refreshes if needed ---
        if refresh_needed:
            print("Settings changed requiring refresh...")
            # Refresh cả hai tree
            if hasattr(self, 'local_tree'):
                self.populate_local_tree(self.current_local_path)
            if hasattr(self, 'github_tree'):
                self.populate_github_tree(self.current_github_context.get('repo'), self.current_github_context.get('path', ""))


    # --- Tạo Widgets ---
    def create_widgets(self):
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(expand=True, fill=BOTH, padx=5, pady=5)

        main_frame = ttk.Frame(self.notebook, padding=0) # Không cần padding ở đây
        self.notebook.add(main_frame, text="Repository Manager")

        # PanedWindow ngang chia đôi panel trái (local) và phải (github)
        main_paned_window = ttk.PanedWindow(main_frame, orient=HORIZONTAL)
        main_paned_window.pack(expand=True, fill=BOTH, pady=(0, 5)) # Thêm padding dưới

        # --- Panel Trái (Local) ---
        left_frame = ttk.Frame(main_paned_window, padding=5)
        main_paned_window.add(left_frame, weight=1)

        local_nav_frame = ttk.Frame(left_frame)
        local_nav_frame.pack(side=TOP, fill=X, pady=(0, 5))

        self.quick_nav_var = tk.StringVar()
        # Lấy danh sách quick access path (cần hàm get_quick_access_paths)
        try:
            quick_nav_options = self.get_quick_access_paths()
            quick_nav_keys = list(quick_nav_options.keys())
        except Exception as e:
            print(f"Error getting quick access paths during widget creation: {e}")
            quick_nav_options = {}
            quick_nav_keys = ["Lỗi tải..."]

        self.quick_nav_combo = ttk.Combobox(local_nav_frame, textvariable=self.quick_nav_var,
                                             values=quick_nav_keys, state="readonly", width=15)
        self.quick_nav_combo.pack(side=LEFT, padx=(0, 5))
        self.quick_nav_combo.bind("<<ComboboxSelected>>", self.on_quick_nav_select)
        self.quick_nav_combo.set("Truy cập nhanh")

        self.local_path_var = tk.StringVar(value=self.current_local_path if self.current_local_path else "My Computer")
        local_path_entry = ttk.Entry(local_nav_frame, textvariable=self.local_path_var, state="normal")
        local_path_entry.pack(side=LEFT, fill=X, expand=True, padx=(0, 5))
        local_path_entry.bind("<Return>", self.navigate_local_from_entry)

        up_button = ttk.Button(local_nav_frame, text="UP", command=self.go_up_local, style="Outline.TButton", width=5)
        up_button.pack(side=LEFT)

        # Khung chứa Treeview cục bộ và scrollbar dọc
        self.local_tree_frame = ttk.Frame(left_frame) # Gán vào self để dùng trong DnD nếu cần sau này
        self.local_tree_frame.pack(expand=True, fill=BOTH)

        self.local_tree = ttk.Treeview(self.local_tree_frame, columns=("Type", "Size", "Modified"), show="tree headings", style="Treeview")
        self.local_tree.heading("#0", text="Tên", command=lambda: self.sort_treeview_column(self.local_tree, "#0", False))
        self.local_tree.heading("Type", text="Loại", command=lambda: self.sort_treeview_column(self.local_tree, "Type", False))
        self.local_tree.heading("Size", text="Kích thước", command=lambda: self.sort_treeview_column(self.local_tree, "Size", True))
        self.local_tree.heading("Modified", text="Ngày sửa", command=lambda: self.sort_treeview_column(self.local_tree, "Modified", False))

        self.local_tree.column("#0", stretch=tk.YES, width=250, anchor='w')
        self.local_tree.column("Type", width=80, anchor='w')
        self.local_tree.column("Size", width=100, anchor='e')
        self.local_tree.column("Modified", width=130, anchor='e')

        local_vscroll = ttk.Scrollbar(self.local_tree_frame, orient=VERTICAL, command=self.local_tree.yview)
        local_hscroll = ttk.Scrollbar(left_frame, orient=HORIZONTAL, command=self.local_tree.xview) # Scroll ngang đặt dưới cùng panel trái
        self.local_tree.configure(yscrollcommand=local_vscroll.set, xscrollcommand=local_hscroll.set)
        local_vscroll.pack(side=RIGHT, fill=Y)
        self.local_tree.pack(expand=True, fill=BOTH)
        local_hscroll.pack(side=BOTTOM, fill=X, pady=(5,0))

        # Bind sự kiện cho local tree
        self.local_tree.bind("<Double-1>", self.on_local_item_double_click)
        self.local_tree.bind("<Button-3>", self.show_local_context_menu)
        self.local_tree.bind("<Delete>", self.delete_selected_local_items)


        # --- Panel Phải (GitHub) ---
        right_frame = ttk.Frame(main_paned_window, padding=5)
        main_paned_window.add(right_frame, weight=1)

        github_action_frame = ttk.Frame(right_frame)
        github_action_frame.pack(side=TOP, fill=X, pady=(0,5))

        self.github_path_label_var = tk.StringVar(value="GitHub: Đang tải...")
        github_path_label = ttk.Label(github_action_frame, textvariable=self.github_path_label_var, anchor='w')
        github_path_label.pack(side=LEFT, fill=X, expand=True, padx=(5, 5))

        # Các nút action cho GitHub
        upload_file_button = ttk.Button(github_action_frame, text="Upload File(s)", command=self.upload_files_dialog, style="Outline.TButton")
        upload_file_button.pack(side=RIGHT, padx=(0, 5))
        upload_folder_button = ttk.Button(github_action_frame, text="Upload Folder", command=self.upload_folder_dialog, style="Outline.TButton")
        upload_folder_button.pack(side=RIGHT, padx=(0, 5))
        refresh_gh_button = ttk.Button(github_action_frame, text="🔃Reload", command=self.refresh_github_tree_current_view, style="Outline.TButton")
        refresh_gh_button.pack(side=RIGHT, padx=(0, 5))

        # Khung chứa Treeview GitHub và scrollbar dọc
        self.github_tree_frame = ttk.Frame(right_frame) # Gán vào self
        self.github_tree_frame.pack(expand=True, fill=BOTH)

        self.github_tree = ttk.Treeview(self.github_tree_frame, columns=("Type", "Size", "Path"), show="tree headings", style="Treeview")
        self.github_tree.heading("#0", text="Tên", command=lambda: self.sort_treeview_column(self.github_tree, "#0", False))
        self.github_tree.heading("Type", text="Loại", command=lambda: self.sort_treeview_column(self.github_tree, "Type", False))
        self.github_tree.heading("Size", text="Kích thước", command=lambda: self.sort_treeview_column(self.github_tree, "Size", True))
        self.github_tree.heading("Path", text="Đường dẫn GitHub")

        self.github_tree.column("#0", stretch=tk.YES, width=300, anchor='w') # Tăng width một chút
        self.github_tree.column("Type", width=100, anchor='w')
        self.github_tree.column("Size", width=120, anchor='e')
        self.github_tree.column("Path", width=0, stretch=tk.NO, minwidth=0)

        github_vscroll = ttk.Scrollbar(self.github_tree_frame, orient=VERTICAL, command=self.github_tree.yview)
        github_hscroll = ttk.Scrollbar(right_frame, orient=HORIZONTAL, command=self.github_tree.xview) # Scroll ngang đặt dưới panel phải
        self.github_tree.configure(yscrollcommand=github_vscroll.set, xscrollcommand=github_hscroll.set)
        github_vscroll.pack(side=RIGHT, fill=Y)
        self.github_tree.pack(expand=True, fill=BOTH)
        github_hscroll.pack(side=BOTTOM, fill=X, pady=(5,0))

        # Bind sự kiện cho github tree
        self.github_tree.bind("<Double-1>", self.on_github_item_double_click)
        self.github_tree.bind("<Button-3>", self.show_github_context_menu)
        self.github_tree.bind("<Delete>", self.delete_selected_github_items_prompt)


        # --- Khung Status Log (Đặt dưới PanedWindow chính) ---
        status_log_frame = ttk.LabelFrame(main_frame, text=" Nhật ký Hoạt động🔤", padding=5)
        # Pack dưới cùng, fill X, không expand Y nhiều
        status_log_frame.pack(side=BOTTOM, fill=X, expand=False, pady=(5, 0), padx=5)

        self.status_log_area = scrolledtext.ScrolledText(
            status_log_frame, wrap=tk.WORD, height=6, state=tk.DISABLED, # Giảm chiều cao mặc định
            relief=tk.FLAT
        )
        self.status_log_area.pack(expand=True, fill=BOTH)
        # Apply font
        log_font_family = self.default_font.actual("family")
        log_font_size = max(8, self.settings.get("font_size", 10) - 1)
        self.status_log_area.config(font=(log_font_family, log_font_size))
        # Configure tags
        self.status_log_area.tag_config("INFO", foreground=self.style.colors.info)
        self.status_log_area.tag_config("SUCCESS", foreground=self.style.colors.success)
        self.status_log_area.tag_config("WARNING", foreground=self.style.colors.warning)
        self.status_log_area.tag_config("ERROR", foreground=self.style.colors.danger)
        self.status_log_area.tag_config("MUTED", foreground=self.style.colors.secondary)


        # --- Status Bar (Dưới cùng) ---
        status_bar_frame = ttk.Frame(self.root, padding=(5, 2)) # Đặt vào root thay vì main_frame
        status_bar_frame.pack(side=BOTTOM, fill=X)
        self.status_var = tk.StringVar(value="Sẵn sàng")
        status_label = ttk.Label(status_bar_frame, textvariable=self.status_var, anchor=W, style="Status.TLabel")
        status_label.pack(side=LEFT, fill=X, expand=True)
        self.progress_bar = ttk.Progressbar(status_bar_frame, orient=HORIZONTAL, length=150, mode='determinate')
        # Progress bar sẽ pack/unpack khi cần

        # --- Settings Tab ---
        settings_frame = ttk.Frame(self.notebook, padding=20)
        self.notebook.add(settings_frame, text=" Cài đặt⚙️ ")
        # ... (Giữ nguyên nội dung của Settings Tab: UI, API, Download) ...
        # UI Settings Frame
        ui_frame = ttk.LabelFrame(settings_frame, text="Giao diện & Hiển thị", padding=10)
        ui_frame.pack(fill=X, pady=10)
        # Theme
        theme_frame = ttk.Frame(ui_frame); theme_frame.pack(fill=X, pady=(0, 5))
        theme_label = ttk.Label(theme_frame, text="Chọn Theme:"); theme_label.pack(side=LEFT, padx=5, anchor='w')
        valid_themes = sorted(self.style.theme_names())
        self.theme_combobox = ttk.Combobox(theme_frame, values=valid_themes, state="readonly")
        self.theme_combobox.pack(side=LEFT, padx=5, expand=True, fill=X)
        self.theme_combobox.bind("<<ComboboxSelected>>", self.on_theme_change)
        # Font Size
        font_frame = ttk.Frame(ui_frame); font_frame.pack(fill=X, pady=5)
        font_label = ttk.Label(font_frame, text="Cỡ chữ:"); font_label.pack(side=LEFT, padx=5, anchor='w')
        self.font_size_var_float = tk.DoubleVar(value=float(self.settings.get("font_size", 10)))
        self.font_size_scale = ttk.Scale(font_frame, from_=8, to=20, orient=HORIZONTAL, variable=self.font_size_var_float, command=self.on_font_size_change_live)
        self.font_size_scale.pack(side=LEFT, padx=5, expand=True, fill=X)
        self.font_size_display_var = tk.IntVar(value=self.settings.get("font_size", 10))
        font_value_label = ttk.Label(font_frame, textvariable=self.font_size_display_var, width=3); font_value_label.pack(side=LEFT, padx=5)
        # Icons
        icon_frame = ttk.Frame(ui_frame); icon_frame.pack(fill=X, pady=(5, 0))
        self.show_icons_var = tk.BooleanVar(value=self.settings.get("show_icons", True))
        self.show_icons_checkbutton = ttk.Checkbutton(icon_frame, text=f"Hiển thị Icon ({DRIVE_ICON}/{FOLDER_ICON}/{FILE_ICON}/{REPO_ICON})", variable=self.show_icons_var)
        self.show_icons_checkbutton.pack(side=LEFT, padx=5)

        # API Settings Frame
        api_frame = ttk.LabelFrame(settings_frame, text="GitHub API Token🔑", padding=10)
        api_frame.pack(fill=X, pady=10)
        api_label = ttk.Label(api_frame, text="Personal Access Token:"); api_label.pack(side=LEFT, padx=5)
        self.api_token_entry = ttk.Entry(api_frame, show="*"); self.api_token_entry.pack(side=LEFT, padx=5, expand=True, fill=X)
        self.show_token_var = tk.BooleanVar(value=False)
        show_token_button = ttk.Checkbutton(api_frame, text="Hiện", variable=self.show_token_var, command=self.toggle_token_visibility, style='Toolbutton')
        show_token_button.pack(side=LEFT)

        # Download Settings Frame
        download_frame = ttk.LabelFrame(settings_frame, text="Tải xuống", padding=10)
        download_frame.pack(fill=X, pady=10)
        dl_label = ttk.Label(download_frame, text="Thư mục lưu mặc định:"); dl_label.pack(side=LEFT, padx=5)
        self.default_download_dir_var = tk.StringVar(value=self.settings.get("default_download_dir", os.path.expanduser("~")))
        self.default_download_entry = ttk.Entry(download_frame, textvariable=self.default_download_dir_var, state='readonly')
        self.default_download_entry.pack(side=LEFT, padx=5, expand=True, fill=X)
        browse_button = ttk.Button(download_frame, text="Chọn...", command=self.browse_default_download_dir, style="Outline.TButton")
        browse_button.pack(side=LEFT)

        save_button = ttk.Button(settings_frame, text="Lưu cài đặt & Áp dụng", command=self.save_settings_ui, style="success.TButton")
        save_button.pack(pady=20)


    # --- Sorting Logic ---
    def sort_treeview_column(self, tv, col, is_numeric):
        # --- SỬA ĐỔI: Xử lý icon cho cả local và github tree ---
        if not hasattr(self, 'sort_reverse') or col not in self.sort_reverse:
             if not hasattr(self, 'sort_reverse'): self.sort_reverse = {}
             self.sort_reverse[col] = False

        items = []
        icon_prefixes_to_strip = (DRIVE_ICON + " ", FOLDER_ICON + " ", FILE_ICON + " ", REPO_ICON + " ")
        for k in tv.get_children(''):
            try:
                if col == "#0":
                    text_val = tv.item(k, 'text')
                    value = text_val # Mặc định
                    if self.settings.get("show_icons"):
                        for prefix in icon_prefixes_to_strip:
                            if text_val.startswith(prefix):
                                value = text_val[len(prefix):]
                                break # Chỉ strip một prefix
                    # Xử lý trường hợp đặc biệt ".."
                    if value == "..": value = "" # Sort ".." lên đầu
                else:
                    value = tv.set(k, col)
                items.append((value, k))
            except tk.TclError: continue

        # Clear previous indicators
        for c in tv['columns'] + ('#0',):
             try:
                 heading_options = tv.heading(c)
                 if heading_options and 'text' in heading_options:
                     current_text = heading_options['text']
                     if ' ▲' in current_text or ' ▼' in current_text:
                         tv.heading(c, text=current_text.replace(' ▲', '').replace(' ▼', ''))
             except tk.TclError: pass

        if is_numeric:
            def get_numeric_value(item_tuple):
                val_str = str(item_tuple[0]).split(' ')[0]
                try: return float(val_str.replace(',', ''))
                except (ValueError, TypeError): return -1
            items.sort(key=get_numeric_value, reverse=self.sort_reverse[col])
        else:
            # Sort case-insensitive, đưa ".." lên đầu nếu có
            items.sort(key=lambda x: (x[0] == "", str(x[0]).lower()), reverse=self.sort_reverse[col])

        for index, (val, k) in enumerate(items):
            if tv.exists(k): tv.move(k, '', index)

        self.sort_reverse[col] = not self.sort_reverse[col]
        try:
            heading_options = tv.heading(col)
            if heading_options and 'text' in heading_options:
                 col_name = heading_options['text']
                 indicator = ' ▲' if not self.sort_reverse[col] else ' ▼'
                 tv.heading(col, text=f"{col_name}{indicator}")
        except tk.TclError: pass


    def _determine_github_drop_target(self, tree_widget, event_y_widget):
        """Xác định repo/path đích cho hành động thả/paste/upload trên GitHub Tree."""
        # --- BẮT ĐẦU DEBUG XÁC ĐỊNH MỤC TIÊU ---
        print(f"--- _determine_github_drop_target được gọi với Y={event_y_widget} ---")
        item_id = None
        try:
            # Xác định item ID dưới con trỏ Y trong Treeview
            item_id = tree_widget.identify_row(event_y_widget)
            print(f"ID của dòng xác định được dưới con trỏ: '{item_id}'")
        except Exception as e:
            print(f"Lỗi trong identify_row: {e}")
            pass # Tiếp tục để kiểm tra thả/click vào khoảng trống

        item_type, data = self.parse_item_id(item_id) # Parse ID đã xác định (có thể là None)
        print(f"Kết quả parse ID: Type='{item_type}', Data='{data}'")

        # Trường hợp 1: Click/Thả vào một repo trong danh sách
        if item_type == 'repo':
            print(f"Mục tiêu GitHub: Gốc Repo '{data['repo']}'")
            return True, data['repo'], ""
        # Trường hợp 2: Click/Thả vào một thư mục bên trong repo
        elif item_type == 'gh' and data['type'] == 'dir':
             print(f"Mục tiêu GitHub: Thư mục '{data['repo']}/{data['path']}'")
             return True, data['repo'], data['path']
        # Trường hợp 3: Click/Thả vào một file bên trong repo -> dùng thư mục chứa file đó
        elif item_type == 'gh' and data['type'] == 'file':
             parent_dir = os.path.dirname(data['path']).replace("\\", "/")
             print(f"Mục tiêu GitHub: Thư mục chứa file '{data['repo']}/{parent_dir}'")
             return True, data['repo'], parent_dir
        # Trường hợp 4: Click/Thả vào item 'back' -> dùng thư mục mà 'back' trỏ tới
        elif item_id and item_id.startswith('back|'):
             parent_repo = self.current_github_context.get('repo')
             parent_path = ""
             if data and data['repo'] != 'root': parent_path = data.get('path', '')
             if parent_repo:
                 print(f"Mục tiêu GitHub: Thư mục cha từ item 'back' '{parent_repo}/{parent_path}'")
                 return True, parent_repo, parent_path
             else:
                 # Không thể xác định mục tiêu từ 'back' ở gốc repo list
                 print("Mục tiêu GitHub: Không thể xác định từ item 'back' ở gốc.")
                 return False, None, None
        # Trường hợp 5: Click/Thả vào khoảng trống hoặc item không hợp lệ (placeholder,...)
        else:
            # Kiểm tra ngữ cảnh hiện tại (đang xem repo nào?)
            current_repo = self.current_github_context.get('repo')
            print(f"Click/Thả vào khoảng trống hoặc item không hợp lệ. Ngữ cảnh hiện tại: Repo='{current_repo}'")
            if current_repo:
                # Nếu đang xem bên trong một repo -> đích là đường dẫn hiện tại của repo đó
                current_path = self.current_github_context.get('path', "")
                print(f"Mục tiêu GitHub: Khoảng trống/hiện tại trong repo view '{current_repo}/{current_path}'")
                return True, current_repo, current_path
            else:
                # Nếu đang ở màn hình danh sách repo gốc -> không thể paste/upload vào khoảng trống
                print("Mục tiêu GitHub: Khoảng trống trong danh sách repo - Không hợp lệ")
                return False, None, None
        # --- KẾT THÚC DEBUG XÁC ĐỊNH MỤC TIÊU ---

    # --- THÊM LẠI HÀM NÀY NẾU show_local_context_menu CẦN ---
    def _determine_local_drop_target(self, tree_widget, event_y_widget):
        """Xác định thư mục cục bộ đích cho hành động thả/paste."""
        print(f"--- _determine_local_drop_target được gọi với Y={event_y_widget} ---")
        item_id = None
        try:
             item_id = tree_widget.identify_row(event_y_widget) # Get iid (path) under cursor
             print(f"ID cục bộ dưới con trỏ: '{item_id}'")
        except Exception as e:
             print(f"Lỗi identify_row cục bộ: {e}")
             pass

        if item_id and tree_widget.exists(item_id):
            item_text = tree_widget.item(item_id, 'text')
            # Thả/Paste vào một thư mục hiện có (không phải '..')
            if os.path.isdir(item_id) and item_text != "..":
                if not os.path.islink(item_id): # Đảm bảo không phải link
                    print(f"Mục tiêu cục bộ: Thư mục '{item_id}'")
                    return True, item_id
                else:
                    print(f"Mục tiêu cục bộ: Link '{item_id}' - Không hợp lệ")
                    return False, None
            else:
                # Thả/Paste vào file, gốc ổ đĩa, hoặc '..' -> không hợp lệ
                 print(f"Mục tiêu cục bộ: Item không hợp lệ '{item_text}' ({item_id})")
                 return False, None
        else:
            # Thả/Paste vào khoảng trống -> dùng thư mục hiện tại (nếu không phải 'Máy tính')
            if self.current_local_path is not None:
                print(f"Mục tiêu cục bộ: Khoảng trống, dùng thư mục hiện tại '{self.current_local_path}'")
                return True, self.current_local_path
            else:
                print("Mục tiêu cục bộ: Khoảng trống trong view 'Máy tính' - Không hợp lệ")
                return False, None # Không thể paste vào "Máy tính"    


    def get_quick_access_paths(self):
        """Trả về dict tên hiển thị và đường dẫn thực cho quick access."""
        paths = {"My PC": None} # Thêm mục "Máy tính" với path=None
        home = os.path.expanduser("~")
        paths["USER"] = home

        # Platform specific Documents location
        docs = ""
        if platform.system() == "Windows":
            try:
                import ctypes
                from ctypes.wintypes import HWND, HANDLE, DWORD, LPCWSTR, MAX_PATH
                CSIDL_PERSONAL = 5 # My Documents
                SHGFP_TYPE_CURRENT = 0
                buf = ctypes.create_unicode_buffer(MAX_PATH)
                ctypes.windll.shell32.SHGetFolderPathW(None, CSIDL_PERSONAL, None, SHGFP_TYPE_CURRENT, buf)
                docs = buf.value
            except Exception as e:
                print(f"Could not get Documents folder via API: {e}")
                docs = os.path.join(home, "Documents")
        elif platform.system() == "Darwin": docs = os.path.join(home, "Documents")
        else: # Linux/Other
             docs = os.path.join(home, "Documents")
             if not os.path.isdir(docs): # XDG fallback
                 try:
                     xdg_docs = subprocess.check_output(['xdg-user-dir', 'DOCUMENTS'], text=True, stderr=subprocess.DEVNULL).strip()
                     if xdg_docs and os.path.isdir(xdg_docs): docs = xdg_docs
                 except: pass
        if docs and os.path.isdir(docs): paths["My Documents"] = docs

        # Downloads folder
        downloads = ""
        # ... (logic tương tự cho Downloads, dùng xdg-user-dir DOWNLOAD trên Linux) ...
        if platform.system() == "Windows": downloads = os.path.join(home, "Downloads")
        elif platform.system() == "Darwin": downloads = os.path.join(home, "Downloads")
        else:
            downloads = os.path.join(home, "Downloads")
            if not os.path.isdir(downloads):
                 try:
                     xdg_downloads = subprocess.check_output(['xdg-user-dir', 'DOWNLOAD'], text=True, stderr=subprocess.DEVNULL).strip()
                     if xdg_downloads and os.path.isdir(xdg_downloads): downloads = xdg_downloads
                 except: pass
        if downloads and os.path.isdir(downloads): paths["Downloads"] = downloads

        # Desktop folder
        desktop = ""
        # ... (logic tương tự cho Desktop, dùng xdg-user-dir DESKTOP trên Linux) ...
        if platform.system() == "Windows": desktop = os.path.join(home, "Desktop")
        elif platform.system() == "Darwin": desktop = os.path.join(home, "Desktop")
        else:
             desktop = os.path.join(home, "Desktop")
             if not os.path.isdir(desktop):
                 try:
                     xdg_desktop = subprocess.check_output(['xdg-user-dir', 'DESKTOP'], text=True, stderr=subprocess.DEVNULL).strip()
                     if xdg_desktop and os.path.isdir(xdg_desktop): desktop = xdg_desktop
                 except: pass
        if desktop and os.path.isdir(desktop): paths["Desktop"] = desktop


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
            mount_points = []
            try: # Check common mount points
                possible_parents = ["/media", f"/run/media/{os.getlogin()}", "/mnt"]
                for parent in possible_parents:
                    if os.path.isdir(parent):
                        try:
                            for item in os.listdir(parent):
                                p = os.path.join(parent, item)
                                # Basic check: is mount or is dir and not system dirs
                                if os.path.ismount(p) or (os.path.isdir(p) and not os.path.islink(p) and not p.startswith(('/dev', '/proc', '/sys', '/snap'))):
                                     if p not in mount_points: mount_points.append(p)
                        except PermissionError: pass
            except Exception as e: print(f"Error getting Linux mounts: {e}")
            for p in sorted(list(set(mount_points))):
                 item_name = os.path.basename(p) or "Thiết bị"
                 paths[f"Thiết bị ({item_name})"] = p
        elif platform.system() == "Darwin":
             if os.path.isdir("/Volumes"):
                 try:
                     for vol in os.listdir("/Volumes"):
                         p = os.path.join("/Volumes", vol)
                         # Filter out common system volumes/links
                         if os.path.isdir(p) and not os.path.islink(p) and vol not in ["Macintosh HD", "Recovery", "Preboot", "VM"]:
                             paths[f"Volume ({vol})"] = p
                 except PermissionError: print("Permission denied accessing /Volumes")

        return paths

    def get_windows_volume_label(self, drive_path):
        # ... (Giữ nguyên hàm get_windows_volume_label) ...
        if platform.system() != "Windows": return ""
        volume_label = ""
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            buf = ctypes.create_unicode_buffer(1024)
            if kernel32.GetVolumeInformationW(ctypes.c_wchar_p(drive_path), buf, ctypes.sizeof(buf), None, None, None, None, 0):
                 volume_label = buf.value
        except Exception as e: print(f"Could not get volume label for {drive_path}: {e}")
        return volume_label

    # --- ĐƯA LẠI HÀM is_drive_root ---
    def is_drive_root(self, path):
        """Kiểm tra xem path có phải là gốc ổ đĩa/volume không."""
        if not path or not isinstance(path, str): return False
        try:
            abs_path = os.path.abspath(path)
            if platform.system() == "Windows":
                # C:\, D:\, etc.
                return len(abs_path) == 3 and abs_path[1:] == ":\\" and abs_path[0].isalpha()
            elif platform.system() in ["Linux", "Darwin"]:
                # Root filesystem "/"
                if abs_path == os.path.abspath(os.sep): return True
                # Check if it's a known mount point
                try:
                    quick_paths = self.get_quick_access_paths()
                    # So sánh absolute paths
                    return any(os.path.isdir(q_path) and os.path.abspath(q_path) == abs_path
                               for display_name, q_path in quick_paths.items()
                               if "Ổ đĩa" in display_name or "Thiết bị" in display_name or "Volume" in display_name or "Hệ thống (/)" in display_name)
                except Exception: return False # Lỗi khi lấy quick paths
        except Exception: return False
        return False

    # --- Xử lý sự kiện UI (Local) ---
    # --- ĐƯA LẠI CÁC HÀM NÀY ---
    def on_quick_nav_select(self, event=None):
        selection = self.quick_nav_var.get()
        paths = self.get_quick_access_paths()
        target_path = paths.get(selection)
        # Xử lý target_path là None cho "Máy tính"
        self.populate_local_tree(target_path)
        self.quick_nav_combo.set("Truy cập nhanh")
        self.quick_nav_combo.selection_clear()

    def navigate_local_from_entry(self, event=None):
        path_input = self.local_path_var.get().strip()
        if path_input.lower() == "máy tính":
            self.populate_local_tree(None)
        elif os.path.isdir(path_input):
            self.populate_local_tree(path_input)
        else:
            messagebox.showerror("Đường dẫn không hợp lệ", f"'{path_input}' không phải thư mục hợp lệ.", parent=self.root)
            # Reset entry về trạng thái hiện tại
            if self.current_local_path is None: self.local_path_var.set("Máy tính")
            else: self.local_path_var.set(self.current_local_path)

    def go_up_local(self):
        if self.current_local_path is None: return # Đang ở "Máy tính", không lên được
        parent_path = os.path.dirname(self.current_local_path)
        if parent_path == self.current_local_path: # Đã ở gốc "/" trên Linux/Mac
             self.populate_local_tree(None) # Lên "Máy tính" từ gốc "/" ?
             return
        if self.is_drive_root(self.current_local_path):
             self.populate_local_tree(None) # Lên "Máy tính" từ gốc ổ đĩa
        elif os.path.isdir(parent_path):
             self.populate_local_tree(parent_path)
        else:
             self.populate_local_tree(None) # Nếu parent không hợp lệ, về "Máy tính"

    # --- Xử lý sự kiện UI (Chung) ---
    # ... (Giữ nguyên on_theme_change, on_font_size_change_live, toggle_token_visibility, browse_default_download_dir, save_settings_ui) ...
    def on_theme_change(self, event=None):
        self.settings["theme"] = self.theme_combobox.get()
        self.apply_settings()
        # Update log colors based on new theme
        try:
             self.status_log_area.tag_config("INFO", foreground=self.style.colors.info)
             self.status_log_area.tag_config("SUCCESS", foreground=self.style.colors.success)
             self.status_log_area.tag_config("WARNING", foreground=self.style.colors.warning)
             self.status_log_area.tag_config("ERROR", foreground=self.style.colors.danger)
             self.status_log_area.tag_config("MUTED", foreground=self.style.colors.secondary)
        except Exception as e: print(f"Error updating log colors: {e}")


    def on_font_size_change_live(self, value_str):
        size = int(float(value_str))
        self.font_size_display_var.set(size)
        if self.settings["font_size"] != size:
            self.settings["font_size"] = size
            self.apply_settings()

    def toggle_token_visibility(self):
        current_content = self.api_token_entry.get()
        if self.show_token_var.get(): # Show
            real_token = self.settings.get("api_token", "")
            self.api_token_entry.config(show="")
            if current_content == "*******" or not current_content:
                 self.api_token_entry.delete(0, tk.END); self.api_token_entry.insert(0, real_token)
        else: # Hide
            self.api_token_entry.config(show="*")
            real_token = self.settings.get("api_token", "")
            display_value = "*******" if real_token else ""
            if current_content == real_token or current_content != display_value:
                self.api_token_entry.delete(0, tk.END); self.api_token_entry.insert(0, display_value)

    def browse_default_download_dir(self):
         current_dir = self.default_download_dir_var.get()
         if not os.path.isdir(current_dir): current_dir = os.path.expanduser("~")
         new_dir = filedialog.askdirectory(
             title="Chọn Thư Mục Lưu Mặc Định", initialdir=current_dir, parent=self.root)
         if new_dir:
             self.default_download_dir_var.set(new_dir)
             self.settings["default_download_dir"] = new_dir
             self.log_status(f"Đã cập nhật thư mục tải xuống mặc định: {new_dir}", "INFO")

    def save_settings_ui(self):
        self.settings["theme"] = self.theme_combobox.get()
        self.settings["font_size"] = self.font_size_display_var.get()
        self.settings["show_icons"] = self.show_icons_var.get()
        self.settings["default_download_dir"] = self.default_download_dir_var.get()

        entered_token = self.api_token_entry.get()
        if self.show_token_var.get(): self.settings["api_token"] = entered_token
        elif entered_token != "*******": self.settings["api_token"] = entered_token

        self.save_settings()
        self.apply_settings(force_refresh=True) # Force refresh after save
        messagebox.showinfo("Đã lưu", "Cài đặt đã được lưu và áp dụng.", parent=self.root)
        # Cập nhật lại hiển thị token cho đúng
        current_visibility = self.show_token_var.get()
        self.show_token_var.set(not current_visibility) # Tạm đổi
        self.toggle_token_visibility() # Gọi để áp dụng state mới
        self.show_token_var.set(current_visibility) # Đặt lại state cũ
        self.toggle_token_visibility() # Gọi lần nữa để quay về state đúng


    # --- Status Update and Logging ---
    # ... (Giữ nguyên update_status, log_status, process_queue) ...
    def update_status(self, message, progress=None):
        """Updates the one-line status bar."""
        self.status_var.set(message)
        if progress is not None and progress >= 0 and progress <= 100:
            if not self.progress_bar.winfo_ismapped():
                 self.progress_bar.pack(side=RIGHT, padx=5, pady=1)
            self.progress_bar['value'] = progress
            self.progress_bar.config(mode='determinate')
        else:
            self.progress_bar['value'] = 0
            if self.progress_bar.winfo_ismapped():
                 self.progress_bar.pack_forget()
        try:
             self.root.update_idletasks()
        except tk.TclError: pass # Ignore errors during shutdown

    def log_status(self, message, level="INFO"):
        """Appends a message to the status log area."""
        try:
            timestamp = time.strftime("%H:%M:%S")
            log_level = level.upper()
            if log_level not in ["INFO", "SUCCESS", "WARNING", "ERROR", "MUTED"]: log_level = "INFO"

            # Đảm bảo widget còn tồn tại
            if not hasattr(self, 'status_log_area') or not self.status_log_area.winfo_exists(): return

            self.status_log_area.config(state=tk.NORMAL)
            self.status_log_area.insert(tk.END, f"{timestamp} ", ("MUTED",))
            self.status_log_area.insert(tk.END, f"{message}\n", (log_level,))
            self.status_log_area.config(state=tk.DISABLED)
            self.status_log_area.see(tk.END)
        except tk.TclError as e: print(f"Error writing to status log: {e}")
        except Exception as e: print(f"Unexpected error in log_status: {e}")

    def process_queue(self):
        """Processes messages from worker threads."""
        try:
            while True:
                task_id, message, progress, finished, data = update_queue.get_nowait()

                log_level = "INFO"
                if "LỖI" in message or "Error" in message or "failed" in message: log_level = "ERROR"
                elif "thành công" in message.lower() or "OK:" in message or "Hoàn thành" in message: log_level = "SUCCESS"
                elif "Bỏ qua" in message or "Skipping" in message: log_level = "WARNING"

                log_msg_full = f"[Task {task_id}] {message}" if task_id else message
                self.log_status(log_msg_full, log_level)

                status_bar_msg = message; max_len = 80
                if len(status_bar_msg) > max_len: status_bar_msg = status_bar_msg[:max_len-3] + "..."
                if task_id: status_bar_msg = f"Task {task_id}: {status_bar_msg}"
                self.update_status(status_bar_msg, progress)

                if finished:
                    if task_id in self.upload_tasks:
                         self.upload_tasks[task_id]['status'] = message
                         # del self.upload_tasks[task_id] # Có thể xóa task đã xong

                    refresh_target = data.get('refresh_view') if data else None
                    if refresh_target == 'github':
                        refresh_repo = data.get('repo'); refresh_path = data.get('path')
                        current_repo = self.current_github_context.get('repo'); current_path = self.current_github_context.get('path', "")
                        action = data.get('action')

                        if action in ['delete_repo', 'rename_repo']:
                            print("Refreshing repo list due to repo action.")
                            self.populate_github_tree()
                        elif current_repo and current_repo == refresh_repo:
                             action_parent_dir = os.path.dirname(refresh_path).replace("\\", "/") if refresh_path else ""
                             norm_current_path = current_path.strip('/')
                             norm_action_path = refresh_path.strip('/') if refresh_path else ""
                             norm_action_parent = action_parent_dir.strip('/')
                             if norm_action_parent == norm_current_path or norm_action_path == norm_current_path:
                                 print(f"Refreshing current GitHub view ({current_repo}/{current_path})")
                                 self.refresh_github_tree_current_view()
                    elif refresh_target == 'local':
                         # Refresh local view if action happened in current dir or affects drives
                         target_local_path = data.get('path') # Đường dẫn cục bộ bị ảnh hưởng
                         if target_local_path:
                             if self.current_local_path is None and self.is_drive_root(target_local_path):
                                  print("Refreshing 'My Computer' view.")
                                  self.populate_local_tree(None)
                             elif self.current_local_path and os.path.normpath(target_local_path) == os.path.normpath(self.current_local_path):
                                  print(f"Refreshing current local view '{self.current_local_path}'")
                                  self.populate_local_tree(self.current_local_path)
                             elif self.current_local_path and os.path.normpath(os.path.dirname(target_local_path)) == os.path.normpath(self.current_local_path):
                                  print(f"Refreshing current local view '{self.current_local_path}' (parent affected)")
                                  self.populate_local_tree(self.current_local_path)


                update_queue.task_done()
        except queue.Empty: pass
        except Exception as e: print(f"Error in process_queue: {e}")
        finally:
            try: self.root.after(150, self.process_queue)
            except tk.TclError: pass # Ignore errors during shutdown

    # --- Logic Local Explorer ---
    # --- ĐƯA LẠI CÁC HÀM NÀY ---
    def populate_local_tree(self, path):
        """Hiển thị nội dung thư mục cục bộ hoặc danh sách ổ đĩa."""
        for i in self.local_tree.get_children(): self.local_tree.delete(i)
        # Reset sort indicators
        if hasattr(self, 'sort_reverse'):
            for col in self.local_tree['columns'] + ('#0',):
                 try:
                     heading_options = self.local_tree.heading(col)
                     if heading_options and 'text' in heading_options: self.local_tree.heading(col, text=heading_options['text'].replace(' ▲', '').replace(' ▼', ''))
                 except tk.TclError: pass
            self.sort_reverse = {}

        show_icons = self.settings.get("show_icons", True)
        home_path = os.path.expanduser("~")

        # --- Xử lý View "Máy tính" (path is None) ---
        if path is None:
            self.current_local_path = None
            self.local_path_var.set("Máy tính")
            self.log_status("Hiển thị danh sách ổ đĩa/volumes.", "INFO")
            try:
                drives_data = []
                quick_paths = self.get_quick_access_paths() # Lấy lại path mới nhất
                for display_name, drive_path in quick_paths.items():
                    # Lọc các mục là ổ đĩa/volume/thiết bị
                    if display_name == "Máy tính": continue # Bỏ qua mục "Máy tính" trong list
                    if "Ổ đĩa" in display_name or "Thiết bị" in display_name or "Volume" in display_name or "Hệ thống (/)" in display_name:
                         if drive_path and os.path.isdir(drive_path): # Kiểm tra path hợp lệ
                             drives_data.append({'display_name': display_name, 'path': drive_path})

                if not drives_data: # Nếu không tìm thấy ổ đĩa nào
                     self.log_status("Không tìm thấy ổ đĩa/volume.", "WARNING")
                     # Có thể hiển thị thông báo hoặc về Home
                     self.populate_local_tree(home_path); return

                drives_data.sort(key=lambda x: x['display_name']) # Sắp xếp theo tên
                for drive in drives_data:
                    icon_prefix = DRIVE_ICON + " " if show_icons else ""
                    display_text = f"{icon_prefix}{drive['display_name']}"
                    # Dùng path làm iid cho ổ đĩa
                    self.local_tree.insert("", tk.END, text=display_text,
                                           values=("Ổ đĩa", "", ""), iid=drive['path'])
                return # Kết thúc xử lý cho "Máy tính"

            except Exception as e:
                 self.log_status(f"Lỗi khi lấy danh sách ổ đĩa: {e}", "ERROR")
                 messagebox.showerror("Lỗi", f"Không thể lấy danh sách ổ đĩa:\n{e}", parent=self.root)
                 self.populate_local_tree(home_path); return # Về Home nếu lỗi

        # --- Xử lý View Thư mục (path is not None) ---
        try:
             # Chuẩn hóa path và kiểm tra hợp lệ
             abs_path = os.path.abspath(path)
             if not os.path.isdir(abs_path):
                 self.log_status(f"Đường dẫn cục bộ không hợp lệ: {path}", "ERROR")
                 messagebox.showerror("Lỗi", f"Đường dẫn không hợp lệ hoặc không thể truy cập:\n{path}", parent=self.root)
                 self.populate_local_tree(None); return # Về "Máy tính"

             self.current_local_path = abs_path
             self.local_path_var.set(self.current_local_path)
             self.log_status(f"Đang xem thư mục: {self.current_local_path}", "INFO")

             items_data = []
             # Thêm mục ".." nếu không phải gốc
             if not self.is_drive_root(abs_path) and os.path.dirname(abs_path) != abs_path:
                 parent_path = os.path.dirname(abs_path)
                 items_data.append({'name': "..", 'display_text': "..", 'type': "Parent Directory", 'size_str': "", 'modified_str': "", 'full_path': parent_path, 'is_dir': True, 'sort_name': ""}) # sort "" lên đầu

             # Liệt kê các mục trong thư mục
             for item in os.listdir(abs_path):
                 full_path = os.path.join(abs_path, item)
                 icon_prefix = ""; item_type = "Khác"; is_dir = False
                 try:
                     stat_info = os.stat(full_path) # Lấy stat trước
                     is_link = os.path.islink(full_path) # islink hoạt động tốt hơn trên stat

                     if os.path.isdir(full_path) and not is_link:
                         item_type = "Thư mục"; is_dir = True
                         if show_icons: icon_prefix = FOLDER_ICON + " "
                     elif os.path.isfile(full_path) and not is_link:
                         item_type = "Tập tin"
                         if show_icons: icon_prefix = FILE_ICON + " "
                     elif is_link:
                         item_type = "Liên kết"
                         # Icon có thể là file hoặc folder tùy mục tiêu? Tạm dùng file
                         if show_icons: icon_prefix = FILE_ICON + " "
                     # Bỏ qua các loại khác (socket,...)

                     size_bytes = stat_info.st_size
                     modified_time = stat_info.st_mtime

                     # Format size và modified time
                     item_size_str = self.format_size(size_bytes) if item_type == "Tập tin" else ""
                     modified_str = time.strftime("%Y-%m-%d %H:%M", time.localtime(modified_time)) if modified_time else "N/A"

                     items_data.append({
                         'name': item, 'display_text': f"{icon_prefix}{item}", 'type': item_type,
                         'size_str': item_size_str, 'modified_str': modified_str,
                         'full_path': full_path, 'is_dir': is_dir, 'sort_name': item.lower()
                     })
                 except OSError as e:
                     print(f"Skipping item due to access error: {full_path} - {e}")
                     continue # Bỏ qua item nếu không đọc được stat

             # Sắp xếp: ".." -> Thư mục -> File -> Liên kết -> Khác, sau đó theo tên
             items_data.sort(key=lambda x: (x['name'] != "..", x['type'] != "Thư mục", x['type'] != "Tập tin", x['type'] != "Liên kết", x['sort_name']))

             # Đưa vào Treeview
             for item_data in items_data:
                 self.local_tree.insert("", tk.END, text=item_data['display_text'],
                                        values=(item_data['type'], item_data['size_str'], item_data['modified_str']),
                                        iid=item_data['full_path']) # Dùng full_path làm iid

        except FileNotFoundError:
             self.log_status(f"Lỗi: Đường dẫn cục bộ không tồn tại: {path}", "ERROR")
             messagebox.showerror("Lỗi", f"Đường dẫn không tồn tại: {path}", parent=self.root)
             self.populate_local_tree(None) # Về "Máy tính"
        except PermissionError:
             self.log_status(f"Lỗi: Không có quyền truy cập: {path}", "ERROR")
             messagebox.showerror("Lỗi", f"Không có quyền truy cập vào:\n{path}", parent=self.root)
             # Thử lên thư mục cha nếu có thể
             parent = os.path.dirname(path)
             if parent != path and os.path.isdir(parent): self.populate_local_tree(parent)
             else: self.populate_local_tree(None) # Về "Máy tính" nếu không lên được
        except Exception as e:
             self.log_status(f"Lỗi không xác định khi đọc thư mục cục bộ: {e}", "ERROR")
             import traceback; traceback.print_exc()
             messagebox.showerror("Lỗi", f"Lỗi khi đọc thư mục:\n{e}", parent=self.root)
             self.populate_local_tree(None) # Về "Máy tính"

    def on_local_item_double_click(self, event):
        item_id = self.local_tree.focus()
        if not item_id: return

        item_text = self.local_tree.item(item_id, 'text')
        if item_text == "..":
            self.go_up_local()
            return

        # item_id chính là full_path
        if os.path.isdir(item_id):
            # Xử lý link thư mục? Hiện tại coi như thư mục thường
            self.populate_local_tree(item_id)
        elif os.path.isfile(item_id):
            try:
                print(f"Opening file: {item_id}")
                if platform.system() == "Windows": os.startfile(item_id)
                elif platform.system() == "Darwin": subprocess.call(('open', item_id))
                else: subprocess.call(('xdg-open', item_id))
                self.log_status(f"Đã mở file: {os.path.basename(item_id)}", "INFO")
            except Exception as e:
                self.log_status(f"Lỗi mở file '{os.path.basename(item_id)}': {e}", "ERROR")
                messagebox.showerror("Lỗi mở file", f"Không thể mở '{os.path.basename(item_id)}':\n{e}", parent=self.root)
        # Có thể thêm xử lý cho links ở đây nếu muốn

    def get_selected_local_items(self):
        """Lấy danh sách các đường dẫn cục bộ đang được chọn (bỏ qua '..')."""
        selected_ids = self.local_tree.selection()
        valid_selections = []
        for item_id in selected_ids:
            if self.local_tree.exists(item_id) and self.local_tree.item(item_id, 'text') != "..":
                valid_selections.append(item_id) # item_id is the full path
        return tuple(valid_selections)


    # --- Logic GitHub Explorer ---
    # ... (Giữ nguyên các hàm populate_github_tree, on_github_item_double_click, parse_item_id, get_selected_github_items_info, refresh_github_tree_current_view) ...
    # Đảm bảo populate_github_tree dùng đúng icon REPO_ICON, FOLDER_ICON, FILE_ICON
    def populate_github_tree(self, repo_name=None, path=""):
        # ... (Clear tree, reset sort) ...
        for i in self.github_tree.get_children(): self.github_tree.delete(i)
        self.current_github_context = {'repo': repo_name, 'path': path}
        show_icons = self.settings.get("show_icons", True)
        if hasattr(self, 'sort_reverse'):
             for col in self.github_tree['columns'] + ('#0',):
                  try:
                      opts = self.github_tree.heading(col);
                      if opts and 'text' in opts: self.github_tree.heading(col, text=opts['text'].replace(' ▲','').replace(' ▼',''))
                  except: pass
             self.sort_reverse = {}

        if not self.github_handler or not self.github_handler.is_authenticated():
            self.github_tree.insert("", tk.END, text="Vui lòng cấu hình API Token...", iid="placeholder_no_auth")
            self.github_path_label_var.set("GitHub: Chưa xác thực")
            return

        self.github_path_label_var.set(f"GitHub: Đang tải...")
        self.root.update_idletasks()

        # View Repo List
        if repo_name is None:
            self.github_path_label_var.set("Repositories List")
            self.log_status("Đang tải danh sách repositories...", "INFO")
            repos = self.github_handler.get_repos()
            if repos is None: # Error during fetch
                 self.github_tree.insert("", tk.END, text="Lỗi tải repo. Xem Nhật ký.", iid="placeholder_load_repo_fail")
                 self.log_status("Không thể tải danh sách repositories.", "ERROR"); return
            if not repos:
                 self.github_tree.insert("", tk.END, text="Không tìm thấy repository.", iid="placeholder_no_repos")
                 self.log_status("Không có repository nào.", "INFO"); return

            repos.sort(key=lambda r: r.name.lower())
            self.log_status(f"Hiển thị {len(repos)} repositories.", "SUCCESS")
            for repo in repos:
                iid = f"repo_{repo.name}" # Dùng ID cũ cho repo list
                display_text = f"{REPO_ICON} {repo.name}" if show_icons else repo.name
                self.github_tree.insert("", tk.END, text=display_text, values=("Repository", "", repo.name), iid=iid)

        # View Repo Content
        else:
            current_display_path = f"{repo_name}/{path}".strip('/') if path else repo_name
            self.github_path_label_var.set(f"GitHub: {current_display_path}")
            self.log_status(f"Đang tải nội dung: {current_display_path}", "INFO")

            # Back item
            parent_path = os.path.dirname(path).replace("\\", "/") if path else None
            back_iid = "back_placeholder"; back_values = ("", "", ""); back_text=".."
            if path:
                parent_display_name = os.path.basename(parent_path) if parent_path else repo_name
                back_text = f".. (Lên '{parent_display_name}')"
                safe_repo = repo_name.replace('|','_'); safe_parent = parent_path.replace('|','_') if parent_path else ''
                back_iid = f"back|{safe_repo}|{safe_parent}"
                back_values = ("", "", parent_path if parent_path is not None else "")
            else:
                 back_text = ".. (Quay lại danh sách Repos)"
                 back_iid = "back|root"
            self.github_tree.insert("", 0, text=back_text, values=back_values, iid=back_iid)

            # Get contents
            contents = self.github_handler.get_repo_contents(repo_name, path)

            if contents is None: # Error loading
                 self.github_tree.insert("", tk.END, text="Lỗi tải nội dung. Xem Nhật ký.", iid="placeholder_load_content_fail")
                 self.log_status(f"Lỗi tải nội dung cho {current_display_path}.", "ERROR"); return
            if not contents: # Empty list
                 is_repo_root = not path
                 empty_msg = "(Repository này rỗng)" if is_repo_root else "(Thư mục rỗng hoặc không tồn tại)"
                 self.github_tree.insert("", tk.END, text=empty_msg, iid="placeholder_empty_dir")
                 self.log_status(f"Nội dung rỗng cho: {current_display_path}", "INFO"); return

            contents.sort(key=lambda c: (c.type != 'dir', c.name.lower()))
            self.log_status(f"Hiển thị {len(contents)} mục trong {current_display_path}.", "SUCCESS")
            for item in contents:
                item_type = "Thư mục" if item.type == "dir" else "Tập tin"
                icon_prefix = ""
                if show_icons: icon_prefix = (FOLDER_ICON if item.type == "dir" else FILE_ICON) + " "
                item_size_str = self.format_size(item.size) if item.type == "file" else ""
                display_text = f"{icon_prefix}{item.name}"
                safe_repo = repo_name.replace('|','_'); safe_path = item.path.replace('|','_'); safe_sha = item.sha.replace('|', '_')
                item_iid = f"gh|{item.type}|{safe_repo}|{safe_path}|{safe_sha}"
                self.github_tree.insert("", tk.END, text=display_text, values=(item_type, item_size_str, item.path), iid=item_iid)


    def on_github_item_double_click(self, event):
        # ... (Giữ nguyên hàm này, nó dùng parse_item_id) ...
        item_id = self.github_tree.focus()
        if not item_id: return
        item_type, data = self.parse_item_id(item_id)
        if item_type == "back":
            if data['repo'] == "root": self.populate_github_tree()
            else: self.populate_github_tree(repo_name=data['repo'], path=data['path'])
        elif item_type == "repo":
            self.populate_github_tree(repo_name=data['repo'], path="")
        elif item_type == "gh" and data['type'] == "dir":
            self.populate_github_tree(repo_name=data['repo'], path=data['path'])
        elif item_type == "gh" and data['type'] == "file":
             self.show_item_info()
             self.log_status(f"Xem thông tin file: {data['repo']}/{data['path']}", "INFO")
        else: self.log_status(f"Double click trên item không hợp lệ: {item_id}", "WARNING")

    def parse_item_id(self, item_id):
        # ... (Giữ nguyên hàm parse_item_id đã sửa) ...
        if not item_id: return None, None
        try:
            if item_id.startswith("repo_"): # Handle repo item first
                repo_name = item_id[len("repo_"):]
                return "repo", {'id': item_id, 'repo': repo_name, 'path': '', 'type': 'repo', 'sha': None, 'name': repo_name}

            parts = item_id.split("|")
            prefix = parts[0]
            if prefix == "back":
                if len(parts) > 1 and parts[1] == "root": return "back", {'repo': 'root', 'path': ''}
                elif len(parts) == 3:
                    try:
                        values = self.github_tree.item(item_id, 'values')
                        actual_parent_path = values[2] if len(values) > 2 else parts[2].replace('_', '|')
                        current_repo = self.current_github_context.get('repo', parts[1].replace('_', '|'))
                        return "back", {'repo': current_repo, 'path': actual_parent_path}
                    except tk.TclError: return "back", {'repo': parts[1].replace('_', '|'), 'path': parts[2].replace('_', '|')}
                else: return None, None
            elif prefix == "gh" and len(parts) == 5:
                item_type, safe_repo_name, safe_path, safe_sha = parts[1], parts[2], parts[3], parts[4]
                try:
                    item_values = self.github_tree.item(item_id, 'values')
                    actual_path = item_values[2] if len(item_values) > 2 else safe_path.replace('_', '|')
                    display_text = self.github_tree.item(item_id, 'text'); name = display_text
                    if self.settings.get("show_icons"):
                        for icon_prefix in (REPO_ICON + " ", FOLDER_ICON + " ", FILE_ICON + " "):
                            if display_text.startswith(icon_prefix): name = display_text[len(icon_prefix):]; break
                except tk.TclError: actual_path = safe_path.replace('_', '|'); name = os.path.basename(actual_path)
                return "gh", {'id': item_id, 'repo': safe_repo_name.replace('_', '|'), 'path': actual_path, 'type': item_type, 'sha': safe_sha.replace('_', '|'), 'name': name}
            elif prefix.startswith("placeholder_"): return "placeholder", {'id': item_id}
            else: print(f"Warning: Unrecognized item ID format: {item_id}"); return None, None
        except Exception as e: print(f"Error parsing item ID '{item_id}': {e}"); return None, None

    def get_selected_github_items_info(self):
        # ... (Giữ nguyên hàm này) ...
        selected_ids = self.github_tree.selection()
        items_info = []
        for item_id in selected_ids:
            item_type, data = self.parse_item_id(item_id)
            if item_type in ["repo", "gh"]: items_info.append(data)
        return items_info

    def refresh_github_tree_current_view(self):
        # ... (Giữ nguyên hàm này) ...
        repo = self.current_github_context.get('repo'); path = self.current_github_context.get('path', "")
        self.log_status(f"Làm mới chế độ xem GitHub: repo='{repo}', path='{path}'", "INFO")
        self.github_tree.selection_set([])
        self.populate_github_tree(repo, path)

    # --- Context Menus ---
    def show_local_context_menu(self, event):
        # --- ĐƯA LẠI HÀM NÀY VÀ CẬP NHẬT ---
        selection = self.local_tree.selection()
        clicked_item_id = self.local_tree.identify_row(event.y)
        context_menu = tk.Menu(self.root, tearoff=0)

        valid_selection_paths = self.get_selected_local_items() # Lấy các path hợp lệ
        num_selected = len(valid_selection_paths)

        # Actions cho các item được chọn
        if num_selected > 0:
            context_menu.add_command(label=f"Copy ({num_selected} mục)", command=self.copy_local_items)
            context_menu.add_command(label=f"Xóa ({num_selected} mục)", command=self.delete_selected_local_items, foreground='red')
            if num_selected == 1:
                 item_path = valid_selection_paths[0]
                 if not self.is_drive_root(item_path): # Không đổi tên gốc ổ đĩa
                     context_menu.add_command(label="Đổi tên", command=self.rename_local_item)
            context_menu.add_separator()

        # Xác định thư mục đích cho Paste
        paste_target_dir = None
        if clicked_item_id and self.local_tree.exists(clicked_item_id):
            # Nếu click vào một thư mục (không phải '..')
            if os.path.isdir(clicked_item_id) and self.local_tree.item(clicked_item_id, 'text') != "..":
                paste_target_dir = clicked_item_id
        elif self.current_local_path is not None: # Click vào khoảng trống trong thư mục
             paste_target_dir = self.current_local_path
        # Nếu đang ở "Máy tính" (self.current_local_path is None) thì paste_target_dir vẫn là None

        # --- Paste từ GitHub vào Local ---
        if self.clipboard and self.clipboard.get('type') == 'remote':
            if paste_target_dir: # Chỉ cho phép paste vào thư mục hợp lệ
                 num_items = len(self.clipboard['items'])
                 target_name = os.path.basename(paste_target_dir)
                 context_menu.add_command(
                     label=f"Paste ({num_items} mục GitHub) vào '{target_name}'",
                     command=lambda t=paste_target_dir: self.handle_paste_to_local(t)
                 )
                 context_menu.add_separator()
            else: # Không có đích hợp lệ để paste
                context_menu.add_command(label="Paste (Chọn thư mục đích)", state=tk.DISABLED)
                context_menu.add_separator()


        # --- Actions chung cho thư mục hiện tại ---
        if self.current_local_path is not None: # Nếu đang ở trong thư mục
             context_menu.add_command(label="Tạo thư mục mới", command=self.create_new_local_folder)
             context_menu.add_command(label="Làm mới", command=lambda: self.populate_local_tree(self.current_local_path))
        else: # Nếu đang ở "Máy tính"
             context_menu.add_command(label="Làm mới", command=lambda: self.populate_local_tree(None))

        # Hiển thị menu
        if context_menu.index(tk.END) is not None: context_menu.tk_popup(event.x_root, event.y_root)


    def show_github_context_menu(self, event):
        # --- ĐƯA LẠI HÀM NÀY VÀ CẬP NHẬT ---
        selection_info = self.get_selected_github_items_info()
        num_selected = len(selection_info)
        clicked_item_id = self.github_tree.identify_row(event.y)
        clicked_item_type, clicked_item_data = self.parse_item_id(clicked_item_id)

        context_menu = tk.Menu(self.root, tearoff=0)
        repo_context = self.current_github_context.get('repo')
        path_context = self.current_github_context.get('path', "")

        # Xác định mục tiêu cho Paste/Upload
        can_paste_here, paste_target_repo, paste_target_gh_path = self._determine_github_drop_target(self.github_tree, event.y)
        paste_location_display = "vị trí hiện tại"
        if can_paste_here:
            paste_location_display = f"{paste_target_repo}/{paste_target_gh_path}".strip('/') if paste_target_gh_path else paste_target_repo
            if not paste_location_display: paste_location_display = "root"
            paste_location_display = f"'{paste_location_display}'"

        # --- Paste từ Local vào GitHub ---
        if self.clipboard and self.clipboard.get('type') == 'local':
            if can_paste_here:
                num_items = len(self.clipboard['items'])
                context_menu.add_command(
                    label=f"Paste ({num_items} mục Local) vào {paste_location_display}",
                    command=lambda repo=paste_target_repo, path=paste_target_gh_path: self.handle_paste_to_github(repo, path)
                )
            else: # Vị trí click không hợp lệ để paste
                 context_menu.add_command(label="Paste (Chọn vị trí hợp lệ)", state=tk.DISABLED)
            context_menu.add_separator()

        # --- Actions cho các item được chọn ---
        if num_selected == 1:
            item = selection_info[0]
            item_display_name = f"'{item['name']}'"
            context_menu.add_command(label=f"Copy (Chuẩn bị tải) {item_display_name}", command=self.copy_github_items) # Đổi tên Copy rõ hơn
            context_menu.add_command(label=f"Xem thông tin {item_display_name}", command=self.show_item_info)
            context_menu.add_command(label=f"Copy Link GitHub {item_display_name}", command=lambda i=item: self.copy_github_link_to_clipboard(i))

            if item['type'] == 'repo':
                context_menu.add_command(label=f"Đổi tên Repository {item_display_name}", command=lambda i=item: self.rename_github_repo_prompt(i))
                context_menu.add_command(label=f"Xóa Repository {item_display_name}...", command=lambda i=item: self.delete_github_repo_prompt(i), foreground='red')
            elif item['type'] == 'file':
                 context_menu.add_command(label=f"Đổi tên File {item_display_name}", command=lambda i=item: self.rename_github_file_prompt(i))
                 context_menu.add_command(label=f"Tải xuống {item_display_name}", command=self.download_selected_github_items)
                 context_menu.add_command(label=f"Xóa File {item_display_name}", command=self.delete_selected_github_items_prompt, foreground='red')
            elif item['type'] == 'dir':
                 context_menu.add_command(label=f"Tải xuống {item_display_name}", command=self.download_selected_github_items)
                 context_menu.add_command(label=f"Xóa Thư mục {item_display_name}", command=self.delete_selected_github_items_prompt, foreground='red')
            context_menu.add_separator()

        elif num_selected > 1:
            context_menu.add_command(label=f"Copy ({num_selected} mục GitHub)", command=self.copy_github_items)
            context_menu.add_command(label=f"Tải xuống ({num_selected} mục)", command=self.download_selected_github_items)
            # Chỉ xóa file/folder khi chọn nhiều
            if all(item['type'] != 'repo' for item in selection_info):
                context_menu.add_command(label=f"Xóa ({num_selected} mục)", command=self.delete_selected_github_items_prompt, foreground='red')
            context_menu.add_separator()


        # --- Actions dựa trên ngữ cảnh (vị trí click) ---
        if can_paste_here: # Dùng lại biến đã xác định ở trên
             context_menu.add_command(label=f"Upload File(s) vào {paste_location_display}",
                                      command=lambda repo=paste_target_repo, path=paste_target_gh_path: self.upload_files_dialog(repo, path))
             context_menu.add_command(label=f"Upload Folder vào {paste_location_display}",
                                      command=lambda repo=paste_target_repo, path=paste_target_gh_path: self.upload_folder_dialog(repo, path))
             context_menu.add_separator()


        # --- Actions chung ---
        context_menu.add_command(label="Làm mới", command=self.refresh_github_tree_current_view)

        # Show Menu
        if context_menu.index(tk.END) is not None: context_menu.tk_popup(event.x_root, event.y_root)


    # --- Clipboard & Paste Handlers ---
    # --- ĐƯA LẠI CÁC HÀM NÀY ---
    def copy_local_items(self):
        selected_paths = self.get_selected_local_items()
        if selected_paths:
            self.clipboard = {
                'type': 'local',
                'items': [{'path': p, 'name': os.path.basename(p)} for p in selected_paths]
            }
            names = [item['name'] for item in self.clipboard['items']]
            msg = f"Đã copy {len(names)} mục cục bộ: {', '.join(names[:3])}{'...' if len(names) > 3 else ''}"
            self.log_status(msg, "INFO")
            self.update_status(msg) # Cập nhật status bar ngắn gọn
        else:
            self.clipboard = None
            self.update_status("Chưa chọn mục cục bộ nào để copy.")

    def copy_github_items(self):
        selected_items_info = self.get_selected_github_items_info()
        items_to_copy = [item for item in selected_items_info if item['type'] != 'repo'] # Bỏ qua repo

        if items_to_copy:
            self.clipboard = {
                'type': 'remote',
                'items': items_to_copy # Lưu dict info đầy đủ
            }
            names = [item['name'] for item in self.clipboard['items']]
            msg = f"Đã copy {len(names)} mục GitHub (sẵn sàng Paste/Tải): {', '.join(names[:3])}{'...' if len(names) > 3 else ''}"
            self.log_status(msg, "INFO")
            self.update_status(msg)
        else:
            self.clipboard = None
            self.update_status("Chưa chọn file/thư mục GitHub nào để copy.")


    def handle_paste_to_local(self, target_directory):
        """Xử lý Paste GitHub items vào thư mục cục bộ."""
        if not self.clipboard or self.clipboard.get('type') != 'remote':
            self.log_status("Clipboard không chứa mục GitHub hoặc rỗng.", "WARNING"); return
        if not target_directory or not os.path.isdir(target_directory):
             messagebox.showerror("Lỗi", f"Thư mục đích không hợp lệ: {target_directory}", parent=self.root)
             self.log_status(f"Paste thất bại: Thư mục đích không hợp lệ '{target_directory}'", "ERROR"); return

        github_items = self.clipboard.get('items', [])
        if not github_items:
             self.log_status("Clipboard rỗng.", "WARNING"); return

        self.log_status(f"Bắt đầu Paste (tải) {len(github_items)} mục vào '{os.path.basename(target_directory)}'", "INFO")
        # Sử dụng logic download đã có (bao gồm kiểm tra ghi đè)
        self._initiate_download(target_directory, github_items)
        # Không xóa clipboard sau paste, cho phép paste nhiều lần
        # self.clipboard = None

    def handle_paste_to_github(self, target_repo, target_github_path):
        """Xử lý Paste local items vào GitHub."""
        if not self.clipboard or self.clipboard.get('type') != 'local':
            self.log_status("Clipboard không chứa mục cục bộ hoặc rỗng.", "WARNING"); return
        if not target_repo: # Cần repo đích
             messagebox.showerror("Lỗi", "Không xác định được Repository đích để Paste.", parent=self.root)
             self.log_status("Paste thất bại: Không rõ repo đích.", "ERROR"); return

        local_items = self.clipboard.get('items', [])
        if not local_items:
             self.log_status("Clipboard rỗng.", "WARNING"); return

        target_display = f"{target_repo}/{target_github_path}".strip('/') if target_github_path else target_repo
        self.log_status(f"Bắt đầu Paste (upload) {len(local_items)} mục vào '{target_display}'", "INFO")
        # Sử dụng logic upload đã có
        self._initiate_upload(target_repo, target_github_path, local_items)
        # Không xóa clipboard sau paste
        # self.clipboard = None

    # --- Core Upload/Download Initiation (Giữ nguyên) ---
    def _initiate_download(self, target_directory, github_items_info, is_dnd=False):
        # ... (Giữ nguyên hàm _initiate_download đã sửa lỗi) ...
        items_to_download = [item for item in github_items_info if item.get('type') != 'repo']
        if not items_to_download: self.log_status("Không có mục hợp lệ để tải.", "WARNING"); return
        if not target_directory or not os.path.isdir(target_directory):
             messagebox.showerror("Lỗi", f"Thư mục đích không hợp lệ: {target_directory}", parent=self.root)
             self.log_status(f"Tải xuống thất bại: Thư mục đích không hợp lệ '{target_directory}'", "ERROR"); return

        conflicts = []; items_to_process_final = []
        for item in items_to_download:
            local_target_path = os.path.join(target_directory, item['name'])
            conflict = os.path.exists(local_target_path)
            items_to_process_final.append({'info': item, 'conflict': conflict})
            if conflict: conflicts.append(item['name'])

        overwrite_all_confirmed = True; skip_conflicts = False
        if conflicts:
            conflict_list_str = "\n - ".join(conflicts[:5]) + ("\n - ..." if len(conflicts) > 5 else "")
            result = messagebox.askyesnocancel(
                "Xác nhận Ghi đè Cục bộ",
                f"Các mục sau đã tồn tại trong '{os.path.basename(target_directory)}':\n - {conflict_list_str}\n\n"
                "Yes: Ghi đè tất cả.\nNo: Bỏ qua các mục bị trùng.\nCancel: Hủy bỏ.",
                icon='warning', parent=self.root )
            if result is None: self.log_status("Đã hủy tải xuống.", "INFO"); return
            elif result is False: # No (Skip)
                overwrite_all_confirmed = False; skip_conflicts = True
                items_to_process_final = [item for item in items_to_process_final if not item['conflict']]
                if not items_to_process_final: self.log_status("Đã hủy tải xuống (không có mục mới).", "INFO"); return
            # else: Yes (Overwrite) - keep all items

        final_items_info_list = [item['info'] for item in items_to_process_final]
        if not final_items_info_list: self.log_status("Không có mục nào để tải.", "INFO"); return

        self.start_download_thread(target_directory, final_items_info_list, overwrite_all=overwrite_all_confirmed)


    def _initiate_upload(self, target_repo, target_github_path, local_items, is_dnd=False):
        # ... (Giữ nguyên hàm _initiate_upload đã sửa lỗi, bao gồm xác nhận) ...
        if not self.github_handler or not self.github_handler.is_authenticated():
             messagebox.showerror("Lỗi", "Chưa kết nối GitHub.", parent=self.root); return
        if not local_items: self.log_status("Không có mục cục bộ nào được chọn/thả.", "WARNING"); return

        confirm_msg = f"Bạn có muốn upload {len(local_items)} mục cục bộ sau đây lên GitHub không?\n"
        item_names = [item['name'] for item in local_items]
        confirm_msg += "\n - ".join(item_names[:5]) + ("..." if len(item_names) > 5 else "")
        target_display = f"{target_repo}/{target_github_path}".strip('/') if target_github_path else target_repo
        confirm_msg += f"\n\nVào vị trí: '{target_display}'"
        confirm_msg += "\n\nLưu ý: Các file/thư mục trùng tên SẼ BỊ GHI ĐÈ."

        if messagebox.askyesno("Xác nhận Upload", confirm_msg, icon='question', parent=self.root):
             final_local_paths_list = [item['path'] for item in local_items]
             if not final_local_paths_list:
                  self.log_status("Không có đường dẫn hợp lệ để upload.", "WARNING"); return
             self.start_upload_thread(target_repo, target_github_path, final_local_paths_list, overwrite=True) # Luôn ghi đè khi upload
        else:
             self.log_status("Upload đã bị hủy bởi người dùng.", "INFO")


    # --- Local Actions ---
    # --- ĐƯA LẠI CÁC HÀM NÀY ---
    def delete_selected_local_items(self, event=None):
        selected_paths = self.get_selected_local_items()
        if not selected_paths: self.update_status("Chưa chọn mục cục bộ để xóa."); return

        names = [os.path.basename(p) for p in selected_paths]
        confirm_msg = f"Xóa vĩnh viễn {len(names)} mục sau khỏi máy tính?\n\n"
        confirm_msg += "\n - ".join([f"'{name}'" for name in names[:10]])
        if len(names) > 10: confirm_msg += "\n - ..."
        confirm_msg += "\n\nHành động này KHÔNG THỂ hoàn tác!"

        if messagebox.askyesno("Xác nhận Xóa Cục bộ", confirm_msg, icon='warning', parent=self.root):
            deleted_count = 0; errors = []
            affected_dir = self.current_local_path # Thư mục cần refresh

            for path in selected_paths:
                try:
                    item_name = os.path.basename(path)
                    if os.path.isfile(path) or os.path.islink(path): os.remove(path)
                    elif os.path.isdir(path): shutil.rmtree(path)
                    else: continue # Bỏ qua loại không xác định
                    print(f"Deleted local: {path}")
                    deleted_count += 1
                except Exception as e:
                    error_msg = f"Lỗi khi xóa '{item_name}': {e}"; print(error_msg); errors.append(error_msg)

            # Refresh tree view cục bộ
            self.populate_local_tree(affected_dir)

            if not errors:
                msg = f"Đã xóa thành công {deleted_count} mục cục bộ."
                self.log_status(msg, "SUCCESS"); self.update_status(msg)
            else:
                msg = f"Đã xóa {deleted_count} mục, có {len(errors)} lỗi."
                self.log_status(msg + f" Lỗi đầu tiên: {errors[0]}", "ERROR")
                messagebox.showerror("Lỗi Xóa Cục bộ", msg + "\n" + "\n".join(errors[:3]) + ("\n..." if len(errors) > 3 else ""), parent=self.root)
                self.update_status(msg)

    def rename_local_item(self):
        selected_paths = self.get_selected_local_items()
        if len(selected_paths) != 1: return
        old_path = selected_paths[0]
        old_name = os.path.basename(old_path)
        directory = os.path.dirname(old_path)

        if self.is_drive_root(old_path):
             messagebox.showwarning("Không thể đổi tên", "Không thể đổi tên gốc ổ đĩa/volume.", parent=self.root); return

        new_name = simpledialog.askstring("Đổi tên", f"Nhập tên mới cho '{old_name}':", initialvalue=old_name, parent=self.root)

        if new_name and new_name != old_name:
            new_path = os.path.join(directory, new_name)
            if os.path.exists(new_path):
                 messagebox.showerror("Lỗi Đổi Tên", f"Tên '{new_name}' đã tồn tại.", parent=self.root); return
            invalid_chars = '\\/:*?"<>|' if platform.system() == "Windows" else "/"
            if any(char in invalid_chars for char in new_name):
                 messagebox.showerror("Lỗi Đổi Tên", f"Tên không hợp lệ.", parent=self.root); return

            try:
                os.rename(old_path, new_path)
                msg = f"Đã đổi tên '{old_name}' thành '{new_name}'."
                self.log_status(msg, "SUCCESS"); self.update_status(msg)
                self.populate_local_tree(directory) # Refresh
                # Select new item
                if self.local_tree.exists(new_path):
                     self.local_tree.selection_set(new_path); self.local_tree.focus(new_path); self.local_tree.see(new_path)
            except Exception as e:
                 msg = f"Lỗi khi đổi tên '{old_name}': {e}"
                 self.log_status(msg, "ERROR")
                 messagebox.showerror("Lỗi Đổi Tên", f"Không thể đổi tên:\n{e}", parent=self.root)
        else: self.update_status("Đã hủy đổi tên.")

    def create_new_local_folder(self):
        target_directory = self.current_local_path
        if target_directory is None:
             messagebox.showwarning("Hành động không hợp lệ", "Không thể tạo thư mục ở đây.", parent=self.root); return

        folder_name = simpledialog.askstring("Tạo Thư mục Mới", "Nhập tên thư mục:", parent=self.root)

        if folder_name:
            new_folder_path = os.path.join(target_directory, folder_name)
            if os.path.exists(new_folder_path):
                 messagebox.showerror("Lỗi Tạo Thư mục", f"Thư mục '{folder_name}' đã tồn tại.", parent=self.root); return
            invalid_chars = '\\/:*?"<>|' if platform.system() == "Windows" else "/"
            if any(char in invalid_chars for char in folder_name):
                 messagebox.showerror("Lỗi Tạo Thư mục", f"Tên thư mục không hợp lệ.", parent=self.root); return

            try:
                os.makedirs(new_folder_path)
                msg = f"Đã tạo thư mục '{folder_name}'."
                self.log_status(msg, "SUCCESS"); self.update_status(msg)
                self.populate_local_tree(target_directory) # Refresh
                # Select new folder
                if self.local_tree.exists(new_folder_path):
                     self.local_tree.selection_set(new_folder_path); self.local_tree.focus(new_folder_path); self.local_tree.see(new_folder_path)
            except Exception as e:
                 msg = f"Lỗi khi tạo thư mục '{folder_name}': {e}"
                 self.log_status(msg, "ERROR")
                 messagebox.showerror("Lỗi Tạo Thư mục", f"Không thể tạo thư mục:\n{e}", parent=self.root)
        else: self.update_status("Đã hủy tạo thư mục.")

    # --- GitHub Actions (Prompts, Info, Link...) ---
    # ... (Giữ nguyên các hàm: delete_selected_github_items_prompt, delete_github_repo_prompt, rename_github_repo_prompt, rename_github_file_prompt, show_item_info, _get_info_worker, format_size, copy_github_link_to_clipboard, upload_files_dialog, upload_folder_dialog, download_selected_github_items) ...
    # Đảm bảo các hàm này không bị thiếu

    def delete_selected_github_items_prompt(self, event=None):
        selected_items = self.get_selected_github_items_info()
        items_to_delete = [item for item in selected_items if item.get('type') != 'repo']
        if not items_to_delete: self.log_status("Vui lòng chọn file/thư mục GitHub để xóa.", "WARNING"); return
        repo_name = items_to_delete[0]['repo']
        files = [item for item in items_to_delete if item['type'] == 'file']
        dirs = [item for item in items_to_delete if item['type'] == 'dir']
        confirm_msg = f"Xóa {len(items_to_delete)} mục khỏi Repo '{repo_name}':\n"
        if files: confirm_msg += "\nFILES:\n" + "\n".join([f" - '{item['name']}'" for item in files[:5]]) + ("..." if len(files)>5 else "")
        if dirs: confirm_msg += "\n\nTHƯ MỤC:\n" + "\n".join([f" - '{item['name']}'" for item in dirs[:5]]) + ("..." if len(dirs)>5 else "") + "\n(Lưu ý: Chỉ xóa được thư mục rỗng)"
        confirm_msg += "\n\nHành động này KHÔNG THỂ hoàn tác!"
        if messagebox.askyesno("Xác nhận Xóa GitHub", confirm_msg, icon='warning', parent=self.root):
            self.log_status(f"Yêu cầu xóa {len(items_to_delete)} mục trên GitHub...", "INFO")
            for item in items_to_delete: self.start_delete_thread(item['repo'], item['path'], item['sha'])
        else: self.log_status("Hủy thao tác xóa.", "INFO")

    def delete_github_repo_prompt(self, repo_info):
         repo_name = repo_info['name']
         confirm_msg = f"!!! CẢNH BÁO !!!\n\nXóa TOÀN BỘ repository '{repo_name}'?\n" \
                       f"Hành động này KHÔNG THỂ HOÀN TÁC.\n\n" \
                       f"Nhập lại tên repository để xác nhận:"
         confirm_name = simpledialog.askstring("Xác nhận Xóa Repository", confirm_msg, parent=self.root)
         if confirm_name is None: self.log_status(f"Hủy xóa repository '{repo_name}'.", "INFO"); return
         if confirm_name.strip() == repo_name:
             self.log_status(f"Yêu cầu xóa repository '{repo_name}'...", "WARNING")
             self.start_delete_repo_thread(repo_name)
         else:
             self.log_status(f"Hủy xóa repository '{repo_name}'. Tên xác nhận không khớp.", "ERROR")
             messagebox.showerror("Xác nhận thất bại", "Tên repository nhập vào không khớp. Đã hủy.", parent=self.root)

    def rename_github_repo_prompt(self, repo_info):
        old_name = repo_info['name']
        prompt_msg = f"Nhập tên mới cho repository '{old_name}':\n(Chỉ chứa a-z, A-Z, 0-9, -, _, .)"
        new_name_raw = simpledialog.askstring("Đổi tên Repository", prompt_msg, initialvalue=old_name, parent=self.root)
        if not new_name_raw: self.log_status(f"Hủy đổi tên repository '{old_name}'.", "INFO"); return
        new_name = new_name_raw.strip()
        if not re.match(r"^[a-zA-Z0-9_.-]+$", new_name):
             messagebox.showerror("Tên không hợp lệ", "Tên repository chứa ký tự không hợp lệ.", parent=self.root)
             self.log_status(f"Đổi tên repo '{old_name}' thất bại: Tên mới '{new_name}' không hợp lệ.", "ERROR"); return
        if new_name == old_name: self.log_status(f"Tên repository '{old_name}' không đổi.", "INFO"); return
        self.log_status(f"Yêu cầu đổi tên repository '{old_name}' thành '{new_name}'...", "INFO")
        self.start_rename_repo_thread(old_name, new_name)

    def rename_github_file_prompt(self, file_info):
        old_name = file_info['name']; repo_name = file_info['repo']; old_path = file_info['path']
        directory = os.path.dirname(old_path).replace("\\", "/")
        prompt_msg = f"Nhập tên file mới cho '{old_name}':\n(Không chứa ký tự '/')"
        new_name_raw = simpledialog.askstring("Đổi tên File", prompt_msg, initialvalue=old_name, parent=self.root)
        if not new_name_raw: self.log_status(f"Hủy đổi tên file '{old_path}'.", "INFO"); return
        new_name = new_name_raw.strip()
        if not new_name or "/" in new_name:
             messagebox.showerror("Tên không hợp lệ", "Tên file không được trống hoặc chứa '/'.", parent=self.root)
             self.log_status(f"Đổi tên file '{old_path}' thất bại: Tên mới '{new_name}' không hợp lệ.", "ERROR"); return
        if new_name == old_name: self.log_status(f"Tên file '{old_path}' không đổi.", "INFO"); return
        new_path = f"{directory}/{new_name}" if directory else new_name
        path_exists = False
        for iid in self.github_tree.get_children(""):
             itype, idata = self.parse_item_id(iid)
             if itype=='gh' and idata['path'].lower() == new_path.lower(): path_exists = True; break
        if path_exists:
             messagebox.showerror("Tên đã tồn tại", f"Tên '{new_name}' đã tồn tại trên GitHub.", parent=self.root)
             self.log_status(f"Đổi tên file '{old_path}' thất bại: Tên mới '{new_path}' đã tồn tại.", "ERROR"); return
        self.log_status(f"Yêu cầu đổi tên file '{old_path}' thành '{new_path}'...", "INFO")
        self.start_rename_file_thread(repo_name, old_path, new_path, file_info['sha'])

    def show_item_info(self):
         selected = self.get_selected_github_items_info()
         if len(selected) != 1: return
         item = selected[0]
         self.log_status(f"Đang lấy thông tin cho '{item.get('name', item.get('repo', 'Unknown'))}'...", "INFO")
         self.update_status(f"Đang lấy thông tin...", 0)
         thread = threading.Thread(target=self._get_info_worker, args=(item,), daemon=True); thread.start()

    def _get_info_worker(self, item_info):
         # ... (Giữ nguyên hàm này) ...
         repo_name = item_info.get('repo'); path = item_info.get('path', ''); item_type = item_info.get('type')
         info_title = f"Thông tin: {item_info.get('name', repo_name)}"; info_details = f"Loại: {item_type}\nRepo: {repo_name}\n"
         if path: info_details += f"Đường dẫn: {path}\n"
         try:
             if item_type == 'repo':
                 repo_obj, error = self.github_handler.get_repo_info(repo_name);
                 if error: raise Exception(error);
                 if not repo_obj: raise Exception("Không tìm thấy repo.")
                 info_details += f"Mô tả: {repo_obj.description or '(không có)'}\nNgôn ngữ chính: {repo_obj.language or 'N/A'}\n"
                 info_details += f"Nhánh mặc định: {repo_obj.default_branch}\nRiêng tư: {'Có' if repo_obj.private else 'Không'}\n"
                 info_details += f"Stars: {repo_obj.stargazers_count}\nForks: {repo_obj.forks_count}\nURL: {repo_obj.html_url}\n"
                 info_details += f"Clone (HTTPS): {repo_obj.clone_url}\nClone (SSH): {repo_obj.ssh_url}\n"
                 info_details += f"Cập nhật lần cuối: {repo_obj.updated_at}\nNgày tạo: {repo_obj.created_at}\n"
             elif item_type in ['file', 'dir']:
                 item_obj, error = self.github_handler.get_item_info(repo_name, path)
                 if error: raise Exception(error);
                 if not item_obj: raise Exception("Không tìm thấy item.")
                 is_actually_dir = isinstance(item_obj, list); single_file_obj = item_obj if not is_actually_dir else None; dir_contents = item_obj if is_actually_dir else None
                 if item_type == 'file' and single_file_obj:
                      info_details += f"SHA: {single_file_obj.sha}\nKích thước: {self.format_size(single_file_obj.size)}\n"
                      info_details += f"Encoding: {single_file_obj.encoding or 'N/A'}\nURL Tải xuống: {single_file_obj.download_url or 'N/A'}\nURL GitHub: {single_file_obj.html_url or 'N/A'}\n"
                      lines = "(Không thể lấy nội dung)";
                      try:
                          if single_file_obj.size < 2 * 1024 * 1024:
                              update_queue.put((None, f"Đang đếm dòng code cho {item_info['name']}...", 50, False, None))
                              content_bytes = single_file_obj.decoded_content
                              if content_bytes is not None:
                                   try: content_str = content_bytes.decode('utf-8', errors='replace'); lines = len(content_str.splitlines())
                                   except Exception: lines = "(Lỗi giải mã)"
                              else: lines = "(Nội dung rỗng)"
                          else: lines = "(File quá lớn)"
                      except RateLimitExceededException: lines = "(Rate limit)"
                      except Exception as e: lines = f"(Lỗi: {e})"
                      info_details += f"Số dòng (ước tính): {lines}\n"
                 elif item_type == 'dir':
                      if dir_contents is None:
                          repo_handle = self.github_handler.user.get_repo(repo_name); dir_contents = repo_handle.get_contents(path)
                      info_details += f"SHA (thư mục): {item_info.get('sha', 'N/A')}\nURL GitHub: {item_obj.html_url if hasattr(item_obj,'html_url') else 'N/A'}\n"
                      file_count = 0; dir_count = 0; total_size = 0; content_list_str = ""; limit = 20
                      if dir_contents:
                          update_queue.put((None, f"Đang phân tích thư mục {item_info['name']}...", 50, False, None))
                          for i, content in enumerate(dir_contents):
                              if content.type == 'file': file_count += 1; total_size += content.size;
                              elif content.type == 'dir': dir_count += 1;
                              if i < limit: content_list_str += f" - [{'F' if content.type=='file' else 'D'}] {content.name}" + (f" ({self.format_size(content.size)})" if content.type=='file' else "") + "\n"
                          if len(dir_contents) > limit: content_list_str += " - ... (và nhiều hơn nữa)"
                      info_details += f"\n--- Nội dung ---\nTổng số mục: {len(dir_contents)}\nSố File: {file_count}\nSố Thư mục con: {dir_count}\n"
                      info_details += f"Tổng kích thước File (cấp 1): {self.format_size(total_size)}\n"
                      if content_list_str: info_details += f"\nCác mục đầu tiên:\n{content_list_str}"
                      else: info_details += "(Thư mục rỗng)"
             update_queue.put((None, f"Hiển thị thông tin cho '{item_info.get('name', repo_name)}'.", 100, True, None))
             self.root.after(0, lambda t=info_title, d=info_details: messagebox.showinfo(t, d, parent=self.root))
         except RateLimitExceededException:
              msg = "Lỗi: Vượt quá giới hạn Rate Limit API."; update_queue.put((None, msg, 100, True, None))
              self.root.after(0, lambda: messagebox.showerror("Rate Limit", msg, parent=self.root))
         except Exception as e:
             msg = f"Lỗi khi lấy thông tin:\n{e}"; update_queue.put((None, msg, 100, True, None))
             self.root.after(0, lambda: messagebox.showerror("Lỗi Thông Tin", msg, parent=self.root))

    def format_size(self, size_bytes):
         # ... (Giữ nguyên hàm này) ...
         if size_bytes is None: return "N/A"
         try: size_bytes = int(size_bytes)
         except: return "N/A"
         if size_bytes < 1024: return f"{size_bytes} B"
         elif size_bytes < 1024**2: return f"{size_bytes/1024:.1f} KB"
         elif size_bytes < 1024**3: return f"{size_bytes/1024**2:.1f} MB"
         else: return f"{size_bytes/1024**3:.1f} GB"

    def copy_github_link_to_clipboard(self, item_data):
         # ... (Giữ nguyên hàm này) ...
        if not self.github_handler or not self.github_handler.is_authenticated() or not self.github_handler.user:
            self.log_status("Lỗi: Chưa xác thực GitHub để lấy link.", "ERROR"); messagebox.showerror("Lỗi", "Chưa xác thực GitHub.", parent=self.root); return
        try:
            repo_name = item_data.get('repo'); item_type = item_data.get('type'); item_path = item_data.get('path', ''); default_branch = "main"; url = None
            if not repo_name: raise ValueError("Tên repository không hợp lệ.")
            base_url = f"https://github.com/{self.github_handler.user.login}/{repo_name}"
            if item_type == 'repo': url = base_url
            elif item_type == 'dir': url = f"{base_url}/tree/{default_branch}/{item_path}" if item_path else f"{base_url}/tree/{default_branch}"
            elif item_type == 'file': url = f"{base_url}/blob/{default_branch}/{item_path}"
            else: self.log_status(f"Không thể tạo link cho loại item không xác định: {item_type}", "WARNING"); return
            url = url.replace(f"/{default_branch}//", f"/{default_branch}/").rstrip('/')
            self.root.clipboard_clear(); self.root.clipboard_append(url); self.log_status(f"Đã copy link: {url}", "SUCCESS")
        except Exception as e:
            self.log_status(f"Lỗi khi tạo link GitHub: {e}", "ERROR"); messagebox.showerror("Lỗi Copy Link", f"Không thể tạo link GitHub:\n{e}", parent=self.root)

    def upload_files_dialog(self, target_repo=None, target_path=None):
         # ... (Giữ nguyên hàm này) ...
        if not self.github_handler or not self.github_handler.is_authenticated(): messagebox.showerror("Chưa xác thực", "Vui lòng cấu hình API token.", parent=self.root); return
        if target_repo is None or target_path is None:
             target_repo = self.current_github_context.get('repo'); target_path = self.current_github_context.get('path', "")
             if target_repo is None: messagebox.showwarning("Chọn Repository", "Vui lòng vào một repository trước khi upload.", parent=self.root); self.log_status("Upload bị hủy: Chưa chọn repo đích.", "WARNING"); return
        local_files = filedialog.askopenfilenames(title=f"Chọn File để Upload lên '{target_repo}/{target_path}'".strip('/'), parent=self.root)
        if local_files:
            local_items_info = [{'path': p, 'name': os.path.basename(p)} for p in local_files]
            self.log_status(f"Chuẩn bị upload {len(local_items_info)} file(s) lên {target_repo}/{target_path}", "INFO")
            self._initiate_upload(target_repo, target_path, local_items_info)
        else: self.log_status("Upload file bị hủy.", "INFO")

    def upload_folder_dialog(self, target_repo=None, target_path=None):
         # ... (Giữ nguyên hàm này) ...
        if not self.github_handler or not self.github_handler.is_authenticated(): messagebox.showerror("Chưa xác thực", "Vui lòng cấu hình API token.", parent=self.root); return
        if target_repo is None or target_path is None:
             target_repo = self.current_github_context.get('repo'); target_path = self.current_github_context.get('path', "")
             if target_repo is None: messagebox.showwarning("Chọn Repository", "Vui lòng vào một repository trước khi upload.", parent=self.root); self.log_status("Upload bị hủy: Chưa chọn repo đích.", "WARNING"); return
        local_folder = filedialog.askdirectory(title=f"Chọn Thư mục để Upload lên '{target_repo}/{target_path}'".strip('/'), mustexist=True, parent=self.root)
        if local_folder:
            local_items_info = [{'path': local_folder, 'name': os.path.basename(local_folder)}]
            self.log_status(f"Chuẩn bị upload thư mục '{os.path.basename(local_folder)}' lên {target_repo}/{target_path}", "INFO")
            self._initiate_upload(target_repo, target_path, local_items_info)
        else: self.log_status("Upload thư mục bị hủy.", "INFO")

    def download_selected_github_items(self):
         # ... (Giữ nguyên hàm này) ...
        selected_items = self.get_selected_github_items_info(); items_to_process = [item for item in selected_items if item.get('type') != 'repo']
        if not items_to_process: messagebox.showwarning("Chưa chọn", "Vui lòng chọn file/thư mục GitHub để tải.", parent=self.root); return
        initial_dir = self.settings.get("default_download_dir", os.path.expanduser("~"))
        if not os.path.isdir(initial_dir): initial_dir = os.path.expanduser("~")
        target_directory = filedialog.askdirectory(title=f"Chọn thư mục lưu cho {len(items_to_process)} mục", initialdir=initial_dir, parent=self.root)
        if not target_directory: self.log_status("Tải xuống bị hủy.", "INFO"); return
        self._initiate_download(target_directory, items_to_process)

    # --- Threading for background tasks ---
    # ... (Giữ nguyên các hàm start/worker cho Upload, Delete, Download, Rename) ...
    def start_upload_thread(self, repo_name, github_path, local_paths, overwrite):
        # ... (Giữ nguyên) ...
        if not self.github_handler or not self.github_handler.is_authenticated(): messagebox.showerror("Lỗi", "Chưa kết nối GitHub.", parent=self.root); return
        self.task_id_counter += 1; task_id = self.task_id_counter; thread = threading.Thread(target=self._upload_worker, args=(task_id, repo_name, github_path, local_paths, overwrite), daemon=True)
        self.upload_tasks[task_id] = {'thread': thread, 'status': 'Bắt đầu...', 'progress': 0, 'type': 'upload', 'repo': repo_name, 'path': github_path}
        base_display = f"{repo_name}/{github_path}".strip('/') if github_path else repo_name
        update_queue.put((task_id, f"Bắt đầu upload {len(local_paths)} item(s) tới '{base_display}'...", 0, False, None)); thread.start()

    def _upload_worker(self, task_id, repo_name, github_path_base, local_paths_initial, overwrite):
        # ... (Giữ nguyên) ...
        total_items_estimated = 0; processed_count = 0; success_count = 0; errors = []; skipped_count = 0; upload_queue = queue.Queue()
        common_base = os.path.commonpath(local_paths_initial) if len(local_paths_initial)>1 else os.path.dirname(local_paths_initial[0])
        if os.path.isfile(common_base): common_base = os.path.dirname(common_base)
        for local_path in local_paths_initial:
             relative_gh_path = github_path_base
             if os.path.dirname(local_path) != common_base:
                  rel_dir = os.path.relpath(os.path.dirname(local_path), common_base).replace("\\", "/"); relative_gh_path = f"{github_path_base}/{rel_dir}".strip("/")
             upload_queue.put((local_path, relative_gh_path))
             try:
                 if os.path.isfile(local_path): total_items_estimated += 1
                 elif os.path.isdir(local_path): total_items_estimated += sum(len(files) + len(dirs) + 1 for _, dirs, files in os.walk(local_path))
             except OSError: pass
        while not upload_queue.empty():
            local_item_path, current_gh_target_dir = upload_queue.get(); item_name = os.path.basename(local_item_path); relative_display_path = os.path.relpath(local_item_path, common_base).replace("\\", "/")
            current_progress = int((processed_count / total_items_estimated) * 95) if total_items_estimated > 0 else 0
            update_queue.put((task_id, f"Xử lý: {relative_display_path}", current_progress, False, None))
            msg = "" # Define msg before try/except block
            if os.path.isfile(local_item_path):
                update_queue.put((task_id, f"Đang upload: {relative_display_path}", current_progress, False, None))
                success, message = self.github_handler.upload_file(repo_name, local_item_path, current_gh_target_dir, commit_message=f"Upload {relative_display_path}", overwrite=overwrite )
                processed_count += 1
                if success: success_count += 1; msg = f"OK: {relative_display_path}"
                elif message == "exists": skipped_count += 1; msg = f"Bỏ qua (trùng): {relative_display_path}"
                else: errors.append(f"Upload error '{relative_display_path}': {message}"); msg = f"LỖI upload {relative_display_path}: {message}"
                update_queue.put((task_id, msg, int((processed_count / total_items_estimated) * 95), False, None))
            elif os.path.isdir(local_item_path):
                processed_count += 1
                new_gh_dir_for_contents = f"{current_gh_target_dir}/{item_name}".strip('/')
                update_queue.put((task_id, f"Quét thư mục: {relative_display_path}", current_progress, False, None))
                try:
                    sub_items = os.listdir(local_item_path)
                    for sub_item_name in sub_items:
                        sub_local_path = os.path.join(local_item_path, sub_item_name); upload_queue.put((sub_local_path, new_gh_dir_for_contents))
                    # Increment success count for directory processing (even if empty)
                    success_count += 1
                except OSError as e:
                    errors.append(f"Dir read error '{relative_display_path}': {e}"); msg = f"LỖI đọc thư mục {relative_display_path}: {e}"
                    update_queue.put((task_id, msg, current_progress, False, None))
            else:
                processed_count += 1; skipped_count += 1
                update_queue.put((task_id, f"Bỏ qua (loại không hỗ trợ): {relative_display_path}", current_progress, False, None));
            upload_queue.task_done()
        final_message = f"Hoàn thành upload. {success_count} thành công."
        if skipped_count > 0: final_message += f" {skipped_count} bỏ qua."
        if errors: final_message += f" Có {len(errors)} lỗi."; print(f"--- Task {task_id} Upload Errors ---\n" + "\n".join(errors) + "\n------------------------------")
        refresh_data = {'refresh_view': 'github', 'repo': repo_name, 'path': github_path_base, 'action': 'upload'}
        update_queue.put((task_id, final_message, 100, True, refresh_data))

    def start_delete_thread(self, repo_name, github_path, sha):
        # ... (Giữ nguyên) ...
        if not self.github_handler or not self.github_handler.is_authenticated(): return
        self.task_id_counter += 1; task_id = self.task_id_counter; thread = threading.Thread(target=self._delete_worker, args=(task_id, repo_name, github_path, sha), daemon=True)
        self.upload_tasks[task_id] = {'thread': thread, 'status': 'Bắt đầu...', 'progress': 0, 'type': 'delete', 'repo': repo_name, 'path': github_path}
        item_name = os.path.basename(github_path) or github_path; update_queue.put((task_id, f"Bắt đầu xóa '{item_name}' từ '{repo_name}'...", 0, False, None)); thread.start()

    def _delete_worker(self, task_id, repo_name, github_path, sha):
        # ... (Giữ nguyên) ...
        item_name = os.path.basename(github_path) or github_path; update_queue.put((task_id, f"Đang xóa: {item_name}...", 50, False, None))
        success, result_message = self.github_handler.delete_item(repo_name, github_path, sha)
        target_dir = os.path.dirname(github_path).replace("\\", "/"); refresh_data = {'refresh_view': 'github', 'repo': repo_name, 'path': target_dir, 'action': 'delete'} if success else None
        update_queue.put((task_id, result_message, 100, True, refresh_data))

    def start_delete_repo_thread(self, repo_name):
        # ... (Giữ nguyên) ...
        if not self.github_handler or not self.github_handler.is_authenticated(): return
        self.task_id_counter += 1; task_id = self.task_id_counter; thread = threading.Thread(target=self._delete_repo_worker, args=(task_id, repo_name), daemon=True)
        self.upload_tasks[task_id] = {'thread': thread, 'status': 'Bắt đầu...', 'progress': 0, 'type': 'delete_repo', 'repo': repo_name}
        update_queue.put((task_id, f"Bắt đầu xóa repository '{repo_name}'...", 0, False, None)); thread.start()

    def _delete_repo_worker(self, task_id, repo_name):
        # ... (Giữ nguyên) ...
        update_queue.put((task_id, f"Đang xóa repository: {repo_name}...", 50, False, None))
        success, result_message = self.github_handler.delete_repo(repo_name)
        refresh_data = {'refresh_view': 'github', 'repo': None, 'path': None, 'action': 'delete_repo'} if success else None
        update_queue.put((task_id, result_message, 100, True, refresh_data))

    def start_rename_repo_thread(self, old_name, new_name):
         # ... (Giữ nguyên) ...
         if not self.github_handler or not self.github_handler.is_authenticated(): return
         self.task_id_counter += 1; task_id = self.task_id_counter; thread = threading.Thread(target=self._rename_repo_worker, args=(task_id, old_name, new_name), daemon=True)
         self.upload_tasks[task_id] = {'thread': thread, 'status': 'Bắt đầu...', 'progress': 0, 'type': 'rename_repo', 'repo': old_name}
         update_queue.put((task_id, f"Bắt đầu đổi tên repo '{old_name}' thành '{new_name}'...", 0, False, None)); thread.start()

    def _rename_repo_worker(self, task_id, old_name, new_name):
         # ... (Giữ nguyên) ...
         update_queue.put((task_id, f"Đang đổi tên repo '{old_name}' thành '{new_name}'...", 50, False, None))
         success, result_message = self.github_handler.rename_repo(old_name, new_name)
         refresh_data = {'refresh_view': 'github', 'repo': None, 'path': None, 'action': 'rename_repo'} if success else None
         update_queue.put((task_id, result_message, 100, True, refresh_data))

    def start_rename_file_thread(self, repo_name, old_path, new_path, sha):
         # ... (Giữ nguyên) ...
         if not self.github_handler or not self.github_handler.is_authenticated(): return
         self.task_id_counter += 1; task_id = self.task_id_counter; thread = threading.Thread(target=self._rename_file_worker, args=(task_id, repo_name, old_path, new_path, sha), daemon=True)
         self.upload_tasks[task_id] = {'thread': thread, 'status': 'Bắt đầu...', 'progress': 0, 'type': 'rename_file', 'repo': repo_name, 'path': os.path.dirname(old_path)}
         update_queue.put((task_id, f"Bắt đầu đổi tên file '{os.path.basename(old_path)}' thành '{os.path.basename(new_path)}'...", 0, False, None)); thread.start()

    def _rename_file_worker(self, task_id, repo_name, old_path, new_path, sha):
        # ... (Giữ nguyên hàm này đã sửa lỗi) ...
        update_queue.put((task_id, f"Đang lấy nội dung file cũ: {os.path.basename(old_path)}...", 25, False, None)); content_bytes = None; msg=""
        try:
            repo = self.github_handler.user.get_repo(repo_name); old_file_content = repo.get_contents(old_path); content_bytes = old_file_content.decoded_content
            if content_bytes is None:
                 if old_file_content.encoding == "base64" and isinstance(old_file_content.content, str): import base64; content_bytes = base64.b64decode(old_file_content.content)
                 else: content_bytes = b''; update_queue.put((task_id, f"File cũ '{os.path.basename(old_path)}' rỗng.", 30, False, None))
        except Exception as e: msg = f"LỖI lấy nội dung file cũ '{os.path.basename(old_path)}': {e}"; update_queue.put((task_id, msg, 100, True, None)); return
        if content_bytes is None: msg = f"LỖI: Không thể lấy nội dung file cũ '{os.path.basename(old_path)}'."; update_queue.put((task_id, msg, 100, True, None)); return

        update_queue.put((task_id, f"Đang tạo file mới: {os.path.basename(new_path)}...", 50, False, None)); commit_message_create = f"Rename: Create {os.path.basename(new_path)}"; new_file_info = None
        try:
            new_file_info = repo.create_file(new_path, commit_message_create, content_bytes)
            if not new_file_info or 'content' not in new_file_info: raise GithubException(status=500, data={'message': 'API create_file không trả về thông tin file mới hợp lệ.'})
            update_queue.put((task_id, f"Đã tạo file mới: {os.path.basename(new_path)}", 75, False, None))
        except GithubException as e:
            msg = f"LỖI tạo file mới '{os.path.basename(new_path)}': {e.status} - {e.data.get('message', '')}" + (" (Tên đã tồn tại?)" if e.status == 422 else "")
            update_queue.put((task_id, msg, 100, True, None)); return
        except Exception as e: msg = f"LỖI không xác định khi tạo file mới '{os.path.basename(new_path)}': {e}"; update_queue.put((task_id, msg, 100, True, None)); return

        update_queue.put((task_id, f"Đang xóa file cũ: {os.path.basename(old_path)}...", 85, False, None)); commit_message_delete = f"Rename: Delete {os.path.basename(old_path)}"
        try:
            repo.delete_file(old_path, commit_message_delete, sha); update_queue.put((task_id, f"Đã xóa file cũ: {os.path.basename(old_path)}", 95, False, None))
        except GithubException as e:
            msg = f"LỖI NGHIÊM TRỌNG: Tạo file mới OK nhưng KHÔNG THỂ xóa file cũ '{os.path.basename(old_path)}': {e.status} - {e.data.get('message', '')}. Cần kiểm tra thủ công!"
            refresh_data = {'refresh_view': 'github', 'repo': repo_name, 'path': os.path.dirname(old_path), 'action': 'rename_file_error'}
            update_queue.put((task_id, msg, 100, True, refresh_data)); return
        except Exception as e:
            msg = f"LỖI NGHIÊM TRỌNG: Tạo file mới OK nhưng lỗi không xác định khi xóa file cũ '{os.path.basename(old_path)}': {e}. Cần kiểm tra thủ công!"
            refresh_data = {'refresh_view': 'github', 'repo': repo_name, 'path': os.path.dirname(old_path), 'action': 'rename_file_error'}
            update_queue.put((task_id, msg, 100, True, refresh_data)); return

        final_message = f"Đổi tên thành công: '{os.path.basename(old_path)}' -> '{os.path.basename(new_path)}'"
        refresh_data = {'refresh_view': 'github', 'repo': repo_name, 'path': os.path.dirname(old_path), 'action': 'rename_file'}
        update_queue.put((task_id, final_message, 100, True, refresh_data))

    def start_download_thread(self, target_directory, items_to_download, overwrite_all):
        # ... (Giữ nguyên) ...
        if not self.github_handler or not self.github_handler.is_authenticated(): return
        self.task_id_counter += 1; task_id = self.task_id_counter; thread = threading.Thread(target=self._download_worker, args=(task_id, target_directory, items_to_download, overwrite_all), daemon=True)
        self.upload_tasks[task_id] = {'thread': thread, 'status': 'Bắt đầu...', 'progress': 0, 'type': 'download', 'path': target_directory}
        update_queue.put((task_id, f"Bắt đầu tải xuống {len(items_to_download)} item(s) vào '{os.path.basename(target_directory)}'...", 0, False, None)); thread.start()

    def _download_worker(self, task_id, target_directory_base, items_to_download_initial, overwrite_all):
        # ... (Giữ nguyên) ...
        total_items_estimated = 0; processed_count = 0; success_count = 0; errors = []; skipped_overwrite = 0
        try: gh = self.github_handler.g; user = self.github_handler.user
        except Exception as e: update_queue.put((task_id, f"Lỗi nghiêm trọng: {e}", 0, True, None)); return
        download_queue = queue.Queue()
        for item_info in items_to_download_initial:
             download_queue.put((item_info, target_directory_base)); total_items_estimated += 1
        while not download_queue.empty():
            item_info, current_local_target_dir = download_queue.get()
            item_name = item_info['name']; item_type = item_info['type']; repo_name = item_info['repo']; github_path = item_info['path']
            local_target_path = os.path.join(current_local_target_dir, item_name); relative_display_path = os.path.relpath(local_target_path, target_directory_base).replace("\\", "/")
            current_progress = int((processed_count / total_items_estimated) * 95) if total_items_estimated > 0 else 0
            update_queue.put((task_id, f"Xử lý: {relative_display_path}", current_progress, False, None))
            if os.path.exists(local_target_path):
                if not overwrite_all:
                    skipped_overwrite += 1; processed_count += 1; update_queue.put((task_id, f"Bỏ qua (trùng): {relative_display_path}", current_progress, False, None)); download_queue.task_done(); continue
                else:
                    update_queue.put((task_id, f"Xóa file cũ: {relative_display_path}", current_progress, False, None))
                    try:
                         if os.path.isfile(local_target_path) or os.path.islink(local_target_path): os.remove(local_target_path)
                         elif os.path.isdir(local_target_path): shutil.rmtree(local_target_path)
                    except Exception as e:
                         processed_count += 1; errors.append(f"Lỗi xóa file cũ '{relative_display_path}': {e}"); update_queue.put((task_id, f"LỖI xóa file cũ: {relative_display_path}: {e}", current_progress, False, None)); download_queue.task_done(); continue
            try:
                repo = user.get_repo(repo_name)
                if item_type == 'file':
                    processed_count += 1; update_queue.put((task_id, f"Đang tải file: {relative_display_path}...", current_progress, False, None)); os.makedirs(os.path.dirname(local_target_path), exist_ok=True)
                    file_content = repo.get_contents(github_path); decoded = file_content.decoded_content
                    if decoded is None:
                         if file_content.encoding == "base64" and isinstance(file_content.content, str): import base64; decoded = base64.b64decode(file_content.content)
                         else: decoded = b'' # Assume empty if cannot decode
                    with open(local_target_path, "wb") as f: f.write(decoded)
                    success_count += 1; update_queue.put((task_id, f"OK: {relative_display_path}", current_progress, False, None))
                elif item_type == 'dir':
                    processed_count += 1; update_queue.put((task_id, f"Quét thư mục GH: {relative_display_path}...", current_progress, False, None)); os.makedirs(local_target_path, exist_ok=True)
                    contents = repo.get_contents(github_path)
                    if contents:
                         update_queue.put((task_id, f"Thêm {len(contents)} mục con từ: {relative_display_path}", current_progress, False, None))
                         if total_items_estimated <= processed_count: total_items_estimated = processed_count + len(contents)
                         else: total_items_estimated += len(contents) -1
                         for content_item in contents:
                              sub_item_info = {'repo': repo_name, 'path': content_item.path, 'type': content_item.type, 'name': content_item.name, 'sha': content_item.sha}
                              download_queue.put((sub_item_info, local_target_path))
                         success_count += 1
                    else: success_count += 1; update_queue.put((task_id, f"OK (Thư mục rỗng): {relative_display_path}", current_progress, False, None))
            except RateLimitExceededException: processed_count += 1; errors.append(f"Rate limit tải '{relative_display_path}'"); update_queue.put((task_id, f"LỖI Rate Limit: {relative_display_path}", current_progress, False, None))
            except GithubException as e: processed_count += 1; errors.append(f"Lỗi GitHub tải '{relative_display_path}': {e.status}"); update_queue.put((task_id, f"LỖI GitHub {e.status}: {relative_display_path}", current_progress, False, None))
            except Exception as e: processed_count += 1; errors.append(f"Lỗi tải xuống '{relative_display_path}': {e}"); update_queue.put((task_id, f"LỖI tải: {relative_display_path}: {e}", current_progress, False, None))
            download_queue.task_done()
        final_message = f"Hoàn thành tải xuống. {success_count} thành công."
        if skipped_overwrite > 0: final_message += f" {skipped_overwrite} bỏ qua (trùng)."
        if errors: final_message += f" Có {len(errors)} lỗi."; print(f"--- Task {task_id} Download Errors ---:\n" + "\n".join(errors) + "\n-------------------------------")
        # Cần refresh local view sau khi download
        refresh_data = {'refresh_view': 'local', 'path': target_directory_base} # Refresh thư mục gốc download
        update_queue.put((task_id, final_message, 100, True, refresh_data))


# --- Chạy ứng dụng ---
if __name__ == "__main__":
    # --- Define load_initial_settings function FIRST ---
    def load_initial_settings():
        """Loads settings from file or returns defaults."""
        try:
            with open(SETTINGS_FILE, 'r') as f: s = json.load(f)
            final_settings = DEFAULT_SETTINGS.copy(); final_settings.update(s)
            if "default_download_dir" not in final_settings or not os.path.isdir(final_settings["default_download_dir"]):
                 final_settings["default_download_dir"] = os.path.expanduser("~")
            return final_settings
        except (FileNotFoundError, json.JSONDecodeError):
            print(f"Settings file '{SETTINGS_FILE}' not found or invalid. Using defaults.")
            s = DEFAULT_SETTINGS.copy(); s["default_download_dir"] = os.path.expanduser("~"); return s
        except Exception as e:
            print(f"Error loading settings: {e}. Using defaults.")
            s = DEFAULT_SETTINGS.copy(); s["default_download_dir"] = os.path.expanduser("~"); return s

    initial_settings = load_initial_settings()
    initial_theme_name = initial_settings.get("theme", DEFAULT_SETTINGS["theme"])

    # --- Luôn sử dụng ttkbootstrap.Window ---
    RootWindowType = tb.Window
    root = None
    try:
        root = RootWindowType(themename=initial_theme_name)
    except tk.TclError:
         print(f"Theme '{initial_theme_name}' not found, using fallback '{DEFAULT_SETTINGS['theme']}'.")
         initial_theme_name = DEFAULT_SETTINGS["theme"]
         initial_settings["theme"] = initial_theme_name
         try: root = RootWindowType(themename=initial_theme_name)
         except Exception as e_fallback: print(f"FATAL: Could not create root window even with fallback theme: {e_fallback}"); sys.exit(1)
    except Exception as e: print(f"FATAL: Error creating root window: {e}"); sys.exit(1)

    # --- Configure root window ---
    root.title("GitHub Repository Manager") # Đổi lại title gốc
    try: root.minsize(1200, 950); root.geometry("1300x1050") # Kích thước gốc
    except Exception as e: print(f"Warning: Could not set window size/minisize: {e}")

    # --- Create the App instance ---
    app = GitHubManagerApp(root)

    # --- Start the main event loop ---
    print("Starting mainloop...")
    root.mainloop()
    print("Mainloop finished.")

# --- END OF REFACTORED FILE main.py ---