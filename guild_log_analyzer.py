import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import pandas as pd
import re
from datetime import datetime
import pytz
import logging
import requests
from io import StringIO

# Configure logging
logging.basicConfig(level=logging.INFO)

# Regular expression pattern to match the log entries
LOG_PATTERN = re.compile(
    r"^\d+\)\s+"
    r"(?P<timestamp>\d{1,2} \w{3} '\d{2} \d{2}:\d{2}[ap]m)\s+:\s+"
    r"(?P<player>.+?)\s+"
    r"(?P<action>(has|is|matches|PROMOTED|DEMOTED|JOINED|Left|Come|died)\s.+)$"
)

def parse_log(file_content):
    data = []

    try:
        for line in file_content.strip().splitlines():
            line = line.strip()
            match = LOG_PATTERN.match(line)
            if match:
                timestamp_str = match.group('timestamp')
                try:
                    timestamp = datetime.strptime(timestamp_str, "%d %b '%y %I:%M%p")
                    # Convert to US Eastern Time
                    local_tz = pytz.timezone('US/Eastern')
                    timestamp = pytz.utc.localize(timestamp).astimezone(local_tz)
                except ValueError:
                    # Handle cases where AM/PM is missing or in incorrect format
                    timestamp = pd.NaT
                    logging.warning(f"Timestamp parsing failed for line: {line}")

                player = match.group('player')
                action = match.group('action')

                # Further split the action into event type and details
                if ';' in action:
                    event_type, details = action.split(';', 1)
                else:
                    event_type = action
                    details = ''

                data.append({
                    'Timestamp': timestamp.strftime('%Y-%m-%d %I:%M:%S %p') if timestamp is not pd.NaT else '',
                    'Player': player.strip(),
                    'Event': event_type.strip(),
                    'Details': details.strip()
                })
            else:
                logging.warning(f"Line didn't match pattern and was skipped: {line}")
    except Exception as e:
        logging.error(f"An error occurred while parsing the log: {e}")
        return pd.DataFrame()

    return pd.DataFrame(data)

def clean_data(df):
    # Extract Level information if available
    df['Level'] = df['Event'].str.extract(r'LVL: (\d+)', expand=False)
    df['Level'] = pd.to_numeric(df['Level'], errors='coerce')

    # Categorize events
    def categorize_event(event_str):
        if 'has died at level' in event_str or 'has died' in event_str or ('has Left the guild' in event_str and '[D]' in event_str):
            return 'Death'
        elif 'Leveled to' in event_str:
            return 'Level Up'
        elif 'JOINED the guild' in event_str or 'has JOINED the guild' in event_str:
            return 'Join'
        elif 'Left the guild' in event_str or 'is no longer in the Guild' in event_str:
            return 'Leave'
        elif 'PROMOTED' in event_str:
            return 'Promotion'
        elif 'DEMOTED' in event_str:
            return 'Demotion'
        elif 'Come ONLINE after being INACTIVE' in event_str:
            return 'Online'
        else:
            return 'Other'

    df['Event Type'] = df['Event'].apply(categorize_event)
    return df

class GuildLogAnalyzerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Guild Log Analyzer")

        self.df = pd.DataFrame()
        self.filtered_df = pd.DataFrame()

        self.create_widgets()
        self.style_widgets()

    def create_widgets(self):
        # General colors
        self.bg_color = '#2C2F33'  # Dark background
        self.fg_color = '#FFFFFF'  # White text
        self.frame_bg = '#23272A'  # Slightly lighter dark
        self.button_bg = '#7289DA'  # Discord blue
        self.button_active_bg = '#99AAB5'  # Lighter blue
        self.entry_bg = '#2C2F33'
        self.entry_fg = '#FFFFFF'

        # Frame for the file selection
        file_frame = ttk.Frame(self.root)
        file_frame.pack(fill='x', padx=5, pady=5)

        self.file_label = ttk.Label(file_frame, text="No file selected")
        self.file_label.pack(side='left', padx=5)

        load_button = ttk.Button(file_frame, text="Load Log File", command=self.load_file)
        load_button.pack(side='right', padx=5)

        # URL Entry and Load Button
        self.url_entry = ttk.Entry(file_frame, width=50)
        self.url_entry.pack(side='left', padx=5)
        load_url_button = ttk.Button(file_frame, text="Load from URL", command=self.load_from_url)
        load_url_button.pack(side='left', padx=5)

        # Frame for filters
        filter_frame = ttk.LabelFrame(self.root, text="Filters")
        filter_frame.pack(fill='x', padx=5, pady=5)

        # Player Name Filter
        ttk.Label(filter_frame, text="Player Name:").grid(row=0, column=0, padx=5, pady=5, sticky='e')
        self.player_entry = ttk.Entry(filter_frame)
        self.player_entry.grid(row=0, column=1, padx=5, pady=5, sticky='w')

        # Event Type Filter
        ttk.Label(filter_frame, text="Event Type:").grid(row=0, column=2, padx=5, pady=5, sticky='e')
        self.event_type_combo = ttk.Combobox(filter_frame, values=["", "Level Up", "Join", "Leave", "Promotion", "Demotion", "Online", "Death", "Other"], state='readonly')
        self.event_type_combo.grid(row=0, column=3, padx=5, pady=5, sticky='w')

        # Date Range Filters
        ttk.Label(filter_frame, text="Start Date (YYYY-MM-DD):").grid(row=1, column=0, padx=5, pady=5, sticky='e')
        self.start_date_entry = ttk.Entry(filter_frame)
        self.start_date_entry.grid(row=1, column=1, padx=5, pady=5, sticky='w')

        ttk.Label(filter_frame, text="End Date (YYYY-MM-DD):").grid(row=1, column=2, padx=5, pady=5, sticky='e')
        self.end_date_entry = ttk.Entry(filter_frame)
        self.end_date_entry.grid(row=1, column=3, padx=5, pady=5, sticky='w')

        # Sort Options
        ttk.Label(filter_frame, text="Sort By:").grid(row=2, column=0, padx=5, pady=5, sticky='e')
        self.sort_by_combo = ttk.Combobox(filter_frame, values=["", "Timestamp", "Player", "Event Type", "Level"], state='readonly')
        self.sort_by_combo.grid(row=2, column=1, padx=5, pady=5, sticky='w')

        # Find String Filter
        ttk.Label(filter_frame, text="Find String:").grid(row=2, column=2, padx=5, pady=5, sticky='e')
        self.find_entry = ttk.Entry(filter_frame)
        self.find_entry.grid(row=2, column=3, padx=5, pady=5, sticky='w')

        # Apply Filters Button
        apply_button = ttk.Button(filter_frame, text="Apply Filters", command=self.apply_filters)
        apply_button.grid(row=3, column=3, padx=5, pady=5, sticky='e')

        # Text Area for Displaying Results
        self.text_area = tk.Text(self.root, wrap='none', bg=self.bg_color, fg=self.fg_color, insertbackground=self.fg_color)
        self.text_area.pack(fill='both', expand=True, padx=5, pady=5)

        # Scrollbars
        x_scroll = ttk.Scrollbar(self.text_area, orient='horizontal', command=self.text_area.xview)
        y_scroll = ttk.Scrollbar(self.text_area, orient='vertical', command=self.text_area.yview)
        self.text_area.configure(xscrollcommand=x_scroll.set, yscrollcommand=y_scroll.set)
        x_scroll.pack(side='bottom', fill='x')
        y_scroll.pack(side='right', fill='y')

        # Export Button
        export_button = ttk.Button(self.root, text="Export to CSV", command=self.export_to_csv)
        export_button.pack(side='right', padx=5, pady=5)

    def style_widgets(self):
        # Apply Discord color scheme
        style = ttk.Style()
        style.theme_use('clam')

        # General colors
        bg_color = self.bg_color  # Dark background
        fg_color = self.fg_color  # White text
        frame_bg = self.frame_bg  # Slightly lighter dark
        button_bg = self.button_bg  # Discord blue
        button_active_bg = self.button_active_bg  # Lighter blue
        entry_bg = self.entry_bg
        entry_fg = self.entry_fg

        # Configure styles
        style.configure('TFrame', background=frame_bg)
        style.configure('TLabel', background=frame_bg, foreground=fg_color)
        style.configure('TLabelFrame', background=frame_bg, foreground=fg_color)
        style.configure('TEntry', fieldbackground=entry_bg, foreground=entry_fg, background=entry_bg)
        style.configure('TCombobox', fieldbackground=entry_bg, foreground=entry_fg, background=entry_bg)
        style.map('TCombobox', fieldbackground=[('readonly', entry_bg)], foreground=[('readonly', entry_fg)])
        style.configure('TCombobox.Downarrow', background=entry_bg)

        # Button styles
        style.configure('TButton', background=button_bg, foreground=fg_color)
        style.map('TButton',
                  background=[('active', button_active_bg)],
                  foreground=[('active', fg_color)])

        # Scrollbar styles
        style.configure('Vertical.TScrollbar', background=bg_color, troughcolor=bg_color, arrowcolor=fg_color)
        style.configure('Horizontal.TScrollbar', background=bg_color, troughcolor=bg_color, arrowcolor=fg_color)
        style.map('Vertical.TScrollbar',
                  background=[('active', frame_bg)],
                  arrowcolor=[('active', fg_color)])
        style.map('Horizontal.TScrollbar',
                  background=[('active', frame_bg)],
                  arrowcolor=[('active', fg_color)])

        self.root.configure(background=bg_color)

    def load_file(self):
        file_path = filedialog.askopenfilename(filetypes=[("Text Files", "*.txt")])
        if file_path:
            self.file_label.config(text=file_path)
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    file_content = f.read()
                self.df = parse_log(file_content)
                if self.df.empty:
                    messagebox.showerror("Error", "Failed to parse the log file.")
                else:
                    self.df = clean_data(self.df)
                    self.apply_filters()
            except Exception as e:
                messagebox.showerror("Error", f"Failed to load the file: {e}")

    def load_from_url(self):
        url = self.url_entry.get().strip()
        if not url:
            messagebox.showwarning("Warning", "Please enter a URL.")
            return
        try:
            response = requests.get(url)
            response.raise_for_status()
            file_content = response.text
            self.df = parse_log(file_content)
            if self.df.empty:
                messagebox.showerror("Error", "Failed to parse the log file from URL.")
            else:
                self.file_label.config(text=url)
                self.df = clean_data(self.df)
                self.apply_filters()
        except requests.exceptions.RequestException as e:
            messagebox.showerror("Error", f"Failed to load from URL: {e}")

    def apply_filters(self):
        if self.df.empty:
            messagebox.showwarning("Warning", "No data to filter. Please load a log file first.")
            return

        self.filtered_df = self.df.copy()

        # Filter by player name
        player_name = self.player_entry.get().strip()
        if player_name:
            self.filtered_df = self.filtered_df[self.filtered_df['Player'].str.contains(player_name, case=False, na=False)]

        # Filter by event type
        event_type = self.event_type_combo.get().strip()
        if event_type:
            self.filtered_df = self.filtered_df[self.filtered_df['Event Type'].str.contains(event_type, case=False, na=False)]

        # Filter by date range
        start_date_str = self.start_date_entry.get().strip()
        end_date_str = self.end_date_entry.get().strip()
        if start_date_str and end_date_str:
            try:
                start_date = pd.to_datetime(start_date_str)
                end_date = pd.to_datetime(end_date_str)
                self.filtered_df['Timestamp'] = pd.to_datetime(self.filtered_df['Timestamp'])
                self.filtered_df = self.filtered_df[(self.filtered_df['Timestamp'] >= start_date) & (self.filtered_df['Timestamp'] <= end_date)]
            except ValueError:
                messagebox.showerror("Error", "Incorrect date format. Please use YYYY-MM-DD.")
                return

        # Filter by find string
        find_string = self.find_entry.get().strip()
        if find_string:
            mask = self.filtered_df.apply(lambda row: row.astype(str).str.contains(find_string, case=False, na=False).any(), axis=1)
            self.filtered_df = self.filtered_df[mask]

        # Apply sorting
        sort_by = self.sort_by_combo.get().strip()
        if sort_by:
            if sort_by in self.filtered_df.columns:
                self.filtered_df = self.filtered_df.sort_values(by=sort_by)
            else:
                messagebox.showerror("Error", f"Cannot sort by {sort_by}. Column does not exist.")
                return

        self.display_data(self.filtered_df)

    def display_data(self, df):
        self.text_area.delete('1.0', tk.END)
        if df.empty:
            self.text_area.insert(tk.END, "No records found with the given filters.")
        else:
            pd.set_option('display.max_rows', None)
            self.text_area.insert(tk.END, df.to_string(index=False))

    def export_to_csv(self):
        if self.filtered_df.empty:
            messagebox.showwarning("Warning", "No data to export. Please load a log file and apply filters.")
            return

        save_path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV Files", "*.csv")])
        if save_path:
            try:
                self.filtered_df.to_csv(save_path, index=False)
                messagebox.showinfo("Success", f"Data exported to {save_path}")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to export data: {e}")

if __name__ == '__main__':
    # Ensure required modules are installed
    try:
        import requests
        import pytz
    except ImportError as e:
        print(f"Required module missing: {e.name}. Please install it using 'pip install {e.name}' and try again.")
        exit(1)

    root = tk.Tk()
    app = GuildLogAnalyzerApp(root)
    root.mainloop()