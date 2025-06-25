import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from PIL import Image, ImageTk
import threading
import shutil
from register import *
from dbHandler import *
import time
import csv
import ntpath
import numpy as np
import cv2
from facerec import detect_faces, train_model, recognize_face, run_osint_analysis

import json
import os
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib import colors
import requests
import queue
import sys
import base64
import subprocess
from datetime import datetime
import sqlite3
from dotenv import load_dotenv
import serpapi

# Load environment variables
load_dotenv()

# Suppress TensorFlow warnings
os.environ['TF_ENABLE_ONEDNN_OPTS'] = '0'

# API credentials
SERPAPI_KEY = os.getenv('SERPAPI_KEY', 'Your-Api-Key')
FACEPP_API_KEY = os.getenv('FACEPP_API_KEY', 'Your-Api-Key')
FACEPP_API_SECRET = os.getenv('FACEPP_API_SECRET', 'Your-Api-Key')
PIMEYES_API_KEY = os.getenv('PIMEYES_API_KEY', 'YOUR_PIMEYES_API_KEY')
SPIDERFOOT_API_KEY = os.getenv('SPIDERFOOT_API_KEY', 'YOUR_SPIDERFOOT_API_KEY')
FACEPP_DETECT_URL = 'https://api-us.faceplusplus.com/facepp/v3/detect'
FACEPP_SEARCH_URL = 'https://api-us.faceplusplus.com/facepp/v3/search'

# Initialize SQLite database for API results
def init_db():
    conn = sqlite3.connect('api_results.db')
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS api_results
                     (image_path TEXT, google_results TEXT, facepp_results TEXT, timestamp TEXT)''')
    conn.commit()
    conn.close()

init_db()

# Global variables
active_page = 0
thread_event = None
left_frame = None
right_frame = None
heading = None
webcam = None
img_label = None
img_read = None
img_list = []
slide_caption = None
slide_control_panel = None
current_slide = -1
voice_sample = None
message_queue = queue.Queue()
dashboard_labels = []
capture_button = None
progress_bar = None

# Initialize Tkinter root
root = tk.Tk()
root.geometry("1500x900+0+0")
root.title("Criminal Face Identification and OSINT Analysis System")
style = ttk.Style()
style.theme_use('clam')
style.configure('TButton', font=('Arial', 15, 'bold'), background='#2196f3', foreground='white')
style.map('TButton', background=[('active', '#091428')], foreground=[('active', 'white')])
style.configure('TLabel', background='#202d42', foreground='white', font=('Arial', 15))
style.configure('TFrame', background='#202d42')
root.configure(bg='#202d42')

# Create Pages
pages = []
for i in range(6):
    pages.append(tk.Frame(root, bg="#202d42"))
    pages[i].pack(side="top", fill="both", expand=True)
    pages[i].place(x=0, y=0, relwidth=1, relheight=1)

def process_message_queue():
    try:
        while True:
            message = message_queue.get_nowait()
            messagebox.showerror("Error", message)
    except queue.Empty:
        pass
    root.after(100, process_message_queue)

def goBack():
    global active_page, thread_event, webcam, img_label, capture_button, progress_bar
    if active_page == 4 and webcam is not None:
        if isinstance(webcam, cv2.VideoCapture) and webcam.isOpened():
            webcam.release()
        webcam = None
        if img_label is not None and img_label.winfo_exists():
            img_label.destroy()
            img_label = None
        if capture_button is not None and capture_button.winfo_exists():
            capture_button.destroy()
            capture_button = None
    if progress_bar is not None and progress_bar.winfo_exists():
        progress_bar.destroy()
        progress_bar = None
    for widget in pages[active_page].winfo_children():
        widget.destroy()
    pages[0].lift()
    active_page = 0
    # Cleanup temporary files
    for temp_file in ['temp_capture.png', 'temp_voice.wav']:
        if os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except:
                pass

def basicPageSetup(pageNo):
    global left_frame, right_frame, heading, progress_bar
    if left_frame is not None and left_frame.winfo_exists():
        left_frame.destroy()
    if right_frame is not None and right_frame.winfo_exists():
        right_frame.destroy()

    back_img = tk.PhotoImage(file="back.png")
    back_button = ttk.Button(pages[pageNo], image=back_img, command=goBack)
    back_button.image = back_img
    back_button.place(x=10, y=10)

    heading = ttk.Label(pages[pageNo], text="", font=('Arial', 20, 'bold'))
    heading.pack()

    content = ttk.Frame(pages[pageNo])
    content.pack(expand=True, fill="both")

    left_frame = ttk.Frame(content)
    left_frame.grid(row=0, column=0, sticky="nsew")

    right_frame = ttk.LabelFrame(content, text="Results", labelanchor="n")
    right_frame.grid(row=0, column=1, sticky="nsew", padx=20, pady=20)

    progress_bar = ttk.Progressbar(content, mode='indeterminate')
    progress_bar.grid(row=1, column=0, columnspan=2, sticky="ew", padx=20, pady=5)

    content.grid_columnconfigure(0, weight=1, uniform="group1")
    content.grid_columnconfigure(1, weight=1, uniform="group1")
    content.grid_rowconfigure(0, weight=1)

def showImage(frame, img_size):
    global img_label, left_frame
    if not left_frame.winfo_exists():
        return
    if frame is None or frame.size == 0:
        message_queue.put("Error: Invalid or empty frame received.")
        return
    try:
        if not isinstance(img_size, tuple) or len(img_size) != 2:
            img_size = (left_frame.winfo_width() - 40, left_frame.winfo_height() - 40)
        if img_size[0] <= 0 or img_size[1] <= 0:
            img_size = (460, 460)
        img = cv2.resize(frame, img_size, interpolation=cv2.INTER_AREA)
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(img)
        img = ImageTk.PhotoImage(img)
        if img_label is None:
            img_label = ttk.Label(left_frame, image=img)
            img_label.image = img
            img_label.pack(padx=20)
        else:
            img_label.configure(image=img)
            img_label.image = img
    except cv2.error as e:
        message_queue.put(f"Image processing failed: {str(e)}")

def getNewSlide(control):
    global img_list, current_slide
    if len(img_list) > 1:
        if control == "prev":
            current_slide = (current_slide-1) % len(img_list)
        else:
            current_slide = (current_slide+1) % len(img_list)
        img_size = (left_frame.winfo_width() - 40, left_frame.winfo_height() - 200)
        showImage(img_list[current_slide], img_size)
        slide_caption.configure(text=f"Image {current_slide+1} of {len(img_list)}")

def record_voice_sample():
    global voice_sample
    try:
        import sounddevice as sd
        from scipy.io import wavfile
        import librosa
        duration = 5
        fs = 44100
        messagebox.showinfo("Recording", "Recording voice sample for 5 seconds. Please speak now.")
        recording = sd.rec(int(duration * fs), samplerate=fs, channels=1)
        sd.wait()
        wavfile.write("temp_voice.wav", fs, recording)
        y, sr = librosa.load("temp_voice.wav")
        mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13)
        voice_sample = np.mean(mfcc, axis=1).tolist()
        messagebox.showinfo("Success", "Voice sample recorded successfully.")
        os.remove("temp_voice.wav")
    except Exception as e:
        message_queue.put(f"Voice recording failed: {str(e)}")

def compare_voice_samples(sample1, sample2):
    if not sample1 or not sample2:
        return 0.0
    sample1 = np.array(sample1)
    sample2 = np.array(sample2)
    distance = np.linalg.norm(sample1 - sample2)
    similarity = max(0, 1 - distance / 100)
    return similarity

def selectMultiImage(opt_menu, menu_var):
    global img_list, current_slide, slide_caption, slide_control_panel
    filetype = [("images", "*.jpg *.jpeg *.png")]
    path_list = filedialog.askopenfilenames(title="Choose at least 5 images", filetypes=filetype)
    if len(path_list) < 5:
        messagebox.showerror("Error", "Choose at least 5 images.")
    else:
        img_list = []
        current_slide = -1
        if slide_control_panel is not None and slide_control_panel.winfo_exists():
            slide_control_panel.destroy()
        for path in path_list:
            img = cv2.imread(path)
            if img is not None and img.size > 0:
                img = cv2.resize(img, (460, 460), interpolation=cv2.INTER_AREA)
                img_list.append(img)
            else:
                message_queue.put(f"Error: Failed to load image {path}")
        menu_var.set("")
        opt_menu['menu'].delete(0, 'end')
        for i in range(len(img_list)):
            ch = f"Image {i+1}"
            opt_menu['menu'].add_command(label=ch, command=tk._setit(menu_var, ch))
            menu_var.set("Image 1")
        if img_list:
            img_size = (left_frame.winfo_width() - 40, left_frame.winfo_height() - 200)
            current_slide += 1
            showImage(img_list[current_slide], img_size)
            slide_control_panel = ttk.Frame(left_frame)
            slide_control_panel.pack()
            back_img = tk.PhotoImage(file="previous.png")
            next_img = tk.PhotoImage(file="next.png")
            prev_slide = ttk.Button(slide_control_panel, image=back_img, command=lambda: getNewSlide("prev"))
            prev_slide.image = back_img
            prev_slide.grid(row=0, column=0, padx=60)
            slide_caption = ttk.Label(slide_control_panel, text=f"Image 1 of {len(img_list)}", foreground="#ff9800")
            slide_caption.grid(row=0, column=1)
            next_slide = ttk.Button(slide_control_panel, image=next_img, command=lambda: getNewSlide("next"))
            next_slide.image = next_img
            next_slide.grid(row=0, column=2, padx=60)

def register(entries, required, menu_var):
    global img_list, voice_sample
    if len(img_list) == 0:
        messagebox.showerror("Error", "Select Images first.")
        return
    entry_data = {}
    for i, entry in enumerate(entries):
        val = entry[1].get()
        if len(val) == 0 and required[i] == 1:
            messagebox.showerror("Field Error", f"Required field missing:\n\n{entry[0]}")
            return
        else:
            entry_data[entry[0]] = val.lower()
    if voice_sample:
        entry_data["voiceprint"] = voice_sample
    else:
        messagebox.showwarning("Warning", "No voice sample recorded. Proceeding without voiceprint.")
        entry_data["voiceprint"] = []
    project_dir = os.path.dirname(os.path.abspath(__file__))
    face_samples_dir = os.path.join(project_dir, "face_samples")
    path = os.path.join(face_samples_dir, "temp_criminal")
    try:
        os.makedirs(face_samples_dir, exist_ok=True)
        if not os.access(face_samples_dir, os.W_OK):
            raise PermissionError(f"No write permission for directory: {face_samples_dir}")
    except Exception as e:
        message_queue.put(f"Failed to create face_samples directory: {str(e)}")
        return
    try:
        os.makedirs(path, exist_ok=True)
        if not os.access(path, os.W_OK):
            raise PermissionError(f"No write permission for directory: {path}")
    except Exception as e:
        message_queue.put(f"Failed to create temp directory: {str(e)}")
        return
    no_face = []
    for i, img in enumerate(img_list):
        id = registerCriminal(img, path, i + 1)
        if id is not None:
            no_face.append(id)
    if len(no_face) > 0:
        no_face_st = ", ".join(f"Image {i}" for i in no_face)
        message_queue.put(f"Registration failed!\n\nFollowing images don't contain a face or face is too small:\n\n{no_face_st}")
        shutil.rmtree(path, ignore_errors=True)
    else:
        rowId = insertData(entry_data)
        if rowId > 0:
            messagebox.showinfo("Success", "Criminal Registered Successfully.")
            final_path = os.path.join(face_samples_dir, entry_data["Name"])
            if os.path.exists(final_path):
                shutil.rmtree(final_path, ignore_errors=True)
            shutil.move(path, final_path)
            criminal_data_dir = os.path.join(project_dir, "criminal_data")
            try:
                os.makedirs(criminal_data_dir, exist_ok=True)
                with open(os.path.join(criminal_data_dir, f"{entry_data['Name']}.json"), "w") as f:
                    json.dump(entry_data, f, indent=4)
            except Exception as e:
                message_queue.put(f"Failed to save criminal data: {str(e)}")
            profile_pics_dir = os.path.join(project_dir, "profile_pics")
            try:
                os.makedirs(profile_pics_dir, exist_ok=True)
            except Exception as e:
                message_queue.put(f"Failed to create profile_pics directory: {str(e)}")
                return
            profile_img_num = int(menu_var.get().split(' ')[1]) - 1
            cv2.imwrite(f"{profile_pics_dir}/criminal {rowId}.png", img_list[profile_img_num])
            refresh_dashboard()
            goBack()
            voice_sample = None
        else:
            shutil.rmtree(path, ignore_errors=True)
            message_queue.put("Some error occurred while storing data.")

def getPage1():
    global active_page, left_frame, right_frame, heading, img_label, voice_sample
    active_page = 1
    img_label = None
    voice_sample = None
    opt_menu = None
    menu_var = tk.StringVar(root)
    pages[1].lift()
    basicPageSetup(1)
    heading.configure(text="Register Criminal")
    right_frame.configure(text="Enter Details")
    btn_grid = ttk.Frame(left_frame)
    btn_grid.pack()
    ttk.Button(btn_grid, text="Select Images", command=lambda: selectMultiImage(opt_menu, menu_var)).grid(row=0, column=0, padx=15, pady=15)
    ttk.Button(btn_grid, text="Record Voice Sample", command=record_voice_sample).grid(row=0, column=1, padx=15, pady=15)
    canvas = tk.Canvas(right_frame, bg="#202d42", highlightthickness=0)
    canvas.pack(side="left", fill="both", expand=True, padx=30)
    scrollbar = ttk.Scrollbar(right_frame, command=canvas.yview)
    scrollbar.pack(side="left", fill="y")
    scroll_frame = ttk.Frame(canvas)
    scroll_win = canvas.create_window((0, 0), window=scroll_frame, anchor='nw')
    canvas.configure(yscrollcommand=scrollbar.set)
    canvas.bind('<Configure>', lambda event, canvas=canvas, win=scroll_win: on_configure(event, canvas, win))
    ttk.Label(scroll_frame, text="* Required Fields", foreground="yellow").pack()
    input_fields = ("Name", "Father's Name", "Mother's Name", "Gender", "DOB(yyyy-mm-dd)",
                    "Identification Mark", "Nationality", "Religion", "Crimes Done", "Profile Image")
    ip_len = len(input_fields)
    required = [1, 0, 0, 0, 0, 0, 0, 0, 0, 0]
    entries = []
    for i, field in enumerate(input_fields):
        row = ttk.Frame(scroll_frame)
        row.pack(side="top", fill="x", pady=15)
        label = tk.Text(row, width=20, height=1, bg="#202d42", fg="#ffffff", font="Arial 13", highlightthickness=0, bd=0)
        label.insert("insert", field)
        label.pack(side="left")
        if required[i] == 1:
            label.tag_configure("star", foreground="yellow", font="Arial 13 bold")
            label.insert("end", "  *", "star")
        label.configure(state="disabled")
        if i != ip_len-1:
            ent = ttk.Entry(row)
            ent.pack(side="right", expand=True, fill="x", padx=10)
            entries.append((field, ent))
        else:
            menu_var.set("Image 1")
            choices = ["Image 1"]
            opt_menu = ttk.OptionMenu(row, menu_var, "Image 1", *choices)
            opt_menu.pack(side="right", fill="x", expand=True, padx=10)
    ttk.Button(scroll_frame, text="Register", command=lambda: register(entries, required, menu_var)).pack(pady=25)

def generate_pdf_report(name, crim_data):
    project_dir = os.path.dirname(os.path.abspath(__file__))
    pdf_path = os.path.join(project_dir, f"criminal_report_{name}.pdf")
    c = canvas.Canvas(pdf_path, pagesize=letter)
    c.setFillColor(colors.darkblue)
    c.rect(0, 750, 612, 40, fill=1)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 20)
    c.drawCentredString(306, 765, "Criminal Profile & OSINT Analysis Report")
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, 710, "Criminal Details")
    c.setFont("Helvetica", 12)
    y = 680
    if not crim_data or not isinstance(crim_data, dict):
        c.drawString(50, y, "No criminal data available.")
    else:
        for key, value in crim_data.items():
            if key != "voiceprint":
                value_str = str(value).capitalize() if value else "N/A"
                c.drawString(50, y, f"{key}: {value_str}")
                y -= 20
    y -= 20
    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, y, "OSINT Results")
    y -= 20
    c.setFont("Helvetica", 12)
    osint_lines = []
    try:
        with open("osint_result.txt", "r", encoding="utf-8") as f:
            lines = f.readlines()
            current_report = []
            in_report = False
            for line in lines:
                if line.startswith(f"=== OSINT Report for {name} ==="):
                    in_report = True
                    current_report = []
                elif line.startswith("=== OSINT Report") and in_report:
                    in_report = False
                    if current_report:
                        osint_lines = current_report
                        break
                elif in_report:
                    current_report.append(line.strip())
    except FileNotFoundError:
        osint_lines = ["OSINT data not available: osint_result.txt not found."]
    except Exception as e:
        osint_lines = [f"Error reading OSINT results: {str(e)}"]
    if not osint_lines:
        osint_lines = ["No OSINT data available for this criminal."]
    for line in osint_lines[:10]:
        c.drawString(50, y, line)
        y -= 20
    c.setFillColor(colors.grey)
    c.setFont("Helvetica", 10)
    c.drawString(50, 50, f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    c.save()
    messagebox.showinfo("Success", f"PDF report generated at: {pdf_path}")

def showCriminalProfile(name):
    top = tk.Toplevel(bg="#202d42")
    top.title("Criminal Profile - OSINT Enhanced")
    top.geometry("1500x900+%d+%d" % (root.winfo_x()+10, root.winfo_y()+10))
    ttk.Label(top, text="Criminal Profile", font=('Arial', 20, 'bold')).pack()
    content = ttk.Frame(top)
    content.pack(expand=True, fill="both")
    content.grid_columnconfigure(0, weight=3, uniform="group1")
    content.grid_columnconfigure(1, weight=5, uniform="group1")
    content.grid_rowconfigure(0, weight=1)
    (id, crim_data) = retrieveData(name)
    project_dir = os.path.dirname(os.path.abspath(__file__))
    profile_pics_dir = os.path.join(project_dir, "profile_pics")
    path = os.path.join(profile_pics_dir, f"criminal {id}.png")
    profile_img = cv2.imread(path)
    if profile_img is None:
        messagebox.showerror("Error", f"Failed to load profile image for criminal {id}.")
        ttk.Label(content, text="Profile image not available.", foreground="red").grid(row=0, column=0)
    else:
        profile_img = cv2.resize(profile_img, (500, 500), interpolation=cv2.INTER_AREA)
        img = cv2.cvtColor(profile_img, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(img)
        img = ImageTk.PhotoImage(img)
        img_label = ttk.Label(content, image=img)
        img_label.image = img
        img_label.grid(row=0, column=0)
    info_frame = ttk.Frame(content)
    info_frame.grid(row=0, column=1, sticky='w')
    for i, item in enumerate(crim_data.items()):
        if item[0] != "voiceprint":
            ttk.Label(info_frame, text=item[0], foreground="yellow", font=('Arial', 15, 'bold')).grid(row=i, column=0, sticky='w')
            ttk.Label(info_frame, text=":", foreground="yellow", font=('Arial', 15, 'bold')).grid(row=i, column=1)
            val = "---" if (item[1] == "") else item[1]
            ttk.Label(info_frame, text=val.capitalize(), font=('Arial', 15)).grid(row=i, column=2, sticky='w')
    ttk.Button(info_frame, text="Generate PDF Report", command=lambda: generate_pdf_report(name, crim_data)).grid(row=len(crim_data)+1, column=0, columnspan=3, pady=20)

def show_recognition_popup(recognized, is_live, attributes, osint_result, google_results, facepp_results):
    popup = tk.Toplevel(bg="#202d42")
    popup.title("Recognition Details")
    popup.geometry("800x600+%d+%d" % (root.winfo_x() + 200, root.winfo_y() + 100))
    ttk.Label(popup, text="Recognition Details", font=('Arial', 20, 'bold')).pack(pady=10)
    content = ttk.Frame(popup)
    content.pack(expand=True, fill="both", padx=20, pady=10)
    canvas = tk.Canvas(content, bg="#202d42", highlightthickness=0)
    canvas.pack(side="left", fill="both", expand=True)
    scrollbar = ttk.Scrollbar(content, command=canvas.yview)
    scrollbar.pack(side="right", fill="y")
    scroll_frame = ttk.Frame(canvas)
    scroll_win = canvas.create_window((0, 0), window=scroll_frame, anchor='nw')
    canvas.configure(yscrollcommand=scrollbar.set)
    canvas.bind('<Configure>', lambda event, canvas=canvas, win=scroll_win: canvas.configure(scrollregion=canvas.bbox('all')))
    row = 0
    for i, crim in enumerate(recognized):
        ttk.Label(scroll_frame, text=f"Criminal {i+1}: {crim[0]} (Confidence: {crim[1]:.2f})", font=('Arial', 12, 'bold')).grid(row=row, column=0, pady=5, sticky='w')
        row += 1
        ttk.Label(scroll_frame, text=f"Liveness: {'Live' if is_live else 'Spoof Detected'}", font=('Arial', 12)).grid(row=row, column=0, pady=2, sticky='w')
        row += 1
        if attributes:
            ttk.Label(scroll_frame, text=f"Age: {attributes.get('age', 'N/A')}", font=('Arial', 12)).grid(row=row, column=0, pady=2, sticky='w')
            row += 1
            ttk.Label(scroll_frame, text=f"Gender: {attributes.get('gender', 'N/A')}", font=('Arial', 12)).grid(row=row, column=0, pady=2, sticky='w')
            row += 1
        ttk.Label(scroll_frame, text="OSINT Results:", font=('Arial', 12, 'bold'), foreground="yellow").grid(row=row, column=0, pady=5, sticky='w')
        row += 1
        if osint_result["metadata"]:
            for key, value in osint_result["metadata"].items():
                ttk.Label(scroll_frame, text=f"{key}: {value}", font=('Arial', 12)).grid(row=row, column=0, pady=2, sticky='w')
                row += 1
        if osint_result["search_results"]:
            for i, link in enumerate(osint_result["search_results"], 1):
                ttk.Label(scroll_frame, text=f"{i}. {link}", font=('Arial', 12), foreground="blue", cursor="hand2").grid(row=row, column=0, pady=2, sticky='w')
                row += 1
        else:
            ttk.Label(scroll_frame, text="No OSINT matches found.", font=('Arial', 12)).grid(row=row, column=0, pady=2, sticky='w')
            row += 1
        ttk.Label(scroll_frame, text="Google Reverse Image Search:", font=('Arial', 12, 'bold'), foreground="yellow").grid(row=row, column=0, pady=5, sticky='w')
        row += 1
        if google_results:
            for result in google_results[:5]:
                ttk.Label(scroll_frame, text=f"URL: {result['link']}\nTitle: {result.get('title', 'N/A')}", font=('Arial', 12), foreground="blue", cursor="hand2").grid(row=row, column=0, pady=2, sticky='w')
                row += 1
        else:
            ttk.Label(scroll_frame, text="No Google matches found.", font=('Arial', 12)).grid(row=row, column=0, pady=2, sticky='w')
            row += 1
        ttk.Label(scroll_frame, text="Face++ Analysis:", font=('Arial', 12, 'bold'), foreground="yellow").grid(row=row, column=0, pady=5, sticky='w')
        row += 1
        if facepp_results:
            for key, value in facepp_results.items():
                ttk.Label(scroll_frame, text=f"{key}: {value}", font=('Arial', 12)).grid(row=row, column=0, pady=2, sticky='w')
                row += 1
        else:
            ttk.Label(scroll_frame, text="No Face++ analysis available.", font=('Arial', 12)).grid(row=row, column=0, pady=2, sticky='w')
            row += 1
        row += 1
    popup.transient(root)
    popup.grab_set()

def startRecognition():
    global img_label, img_read, progress_bar
    print(f"startRecognition called. img_read: {img_read is not None}")
    if img_read is None:
        message_queue.put("No image selected.")
        return
    recognize_btn = find_widget_recursive(left_frame, ttk.Button, "Recognize")
    if recognize_btn:
        recognize_btn.configure(state='disabled')
    def recognition_task():
        try:
            print("Clearing right_frame widgets")
            for wid in right_frame.winfo_children():
                wid.destroy()
            frame = cv2.flip(img_read.copy(), 1, 0)
            print(f"Frame shape after flip: {frame.shape if frame is not None else 'None'}")
            if frame is None or frame.size == 0:
                message_queue.put("Error: Invalid or empty frame for recognition.")
                return
            frame = cv2.resize(frame, (460, 460), interpolation=cv2.INTER_AREA)
            print("Detecting faces...")
            face_coords, gray_frame, eye_coords = detect_faces(frame)
            print(f"Detected faces: {len(face_coords)} coordinates: {face_coords}")
            if not face_coords:  # Safe check for empty array/list
                message_queue.put("Image doesn't contain any face or face is too small.")
            else:
                print("Training model...")
                (model, names) = train_model()
                print(f"Model trained. Names: {names}")
                if model is None:
                    message_queue.put("Model training failed.")
                    return
                print("Recognizing faces...")
                (frame, recognized) = recognize_face(model, frame, gray_frame, face_coords, names, eye_coords)
                is_live = check_liveness(frame, face_coords[0], eye_coords[0] if eye_coords and len(eye_coords) > 0 else [])
                attributes = analyze_face_attributes(frame, face_coords[0]) if face_coords and len(face_coords) > 0 else {}
                img_size = (left_frame.winfo_width() - 40, left_frame.winfo_height() - 40)
                frame = cv2.flip(frame, 1, 0)
                cv2.imwrite("temp_capture.png", frame)
                osint_result = run_osint_search("temp_capture.png", recognized[0][0] if recognized else "")
                google_results = run_google_search("temp_capture.png")
                facepp_results = run_facepp_analysis("temp_capture.png")
                save_api_results("temp_capture.png", google_results, facepp_results)
                root.after(0, lambda: showImage(frame, img_size))
                if not recognized:  # Safe check for empty recognized list
                    message_queue.put("No criminal recognized.")
                root.after(0, lambda: show_recognition_popup(recognized, is_live, attributes, osint_result, google_results, facepp_results))
        except cv2.error as e:
            message_queue.put(f"OpenCV error during recognition: {str(e)}")
        except Exception as e:
            message_queue.put(f"Recognition failed: {str(e)}")
        finally:
            if recognize_btn:
                root.after(0, lambda: recognize_btn.configure(state='normal'))
            if progress_bar:
                root.after(0, lambda: progress_bar.stop())
    if progress_bar:
        progress_bar.start()
    thread = threading.Thread(target=recognition_task)
    thread.start()
def run_google_search(image_path):
    results = []
    try:
        with open(image_path, 'rb') as image_file:
            image_data = base64.b64encode(image_file.read()).decode('utf-8')
        params = {
            'engine': 'google_reverse_image',
            'image_base64': image_data,
            'api_key': SERPAPI_KEY
        }
        client = serpapi.Client()
        response = client.search(params)
        if 'image_results' in response:
            results = [{'link': item['link'], 'title': item.get('title', 'N/A')} for item in response['image_results'][:5]]
    except Exception as e:
        print(f"Google search failed: {str(e)}")
    return results

def run_facepp_analysis(image_path):
    results = {}
    try:
        with open(image_path, 'rb') as image_file:
            files = {'image_file': image_file}
            params = {
                'api_key': Your-Api-Key,
                'api_secret':Your-Api-Key,
                'return_attributes': 'gender,age,emotion,facequality,beauty,ethnicity'
            }
            response = requests.post(FACEPP_DETECT_URL, files=files, data=params)
            response.raise_for_status()
            result = response.json()
            if 'faces' in result and len(result['faces']) > 0:
                face = result['faces'][0]['attributes']
                results = {
                    'Gender': face['gender']['value'],
                    'Age': face['age']['value'],
                    'Emotion': max(face['emotion'].items(), key=lambda x: x[1])[0],
                    'Beauty Score': face['beauty']['male_score' if face['gender']['value'] == 'Male' else 'female_score'],
                    'Ethnicity': face['ethnicity']['value']
                }
    except Exception as e:
        print(f"Face++ analysis failed: {str(e)}")
    return results

def run_facepp_search(image_path):
    results = []
    try:
        with open(image_path, 'rb') as image_file:
            files = {'image_file': image_file}
            params = {
                'api_key': FACEPP_API_KEY,
                'api_secret': FACEPP_API_SECRET,
                'faceset_token': 'YOUR_FACESET_TOKEN'  # Replace with your Face++ faceset token
            }
            response = requests.post(FACEPP_SEARCH_URL, files=files, data=params)
            response.raise_for_status()
            result = response.json()
            if 'results' in result:
                results = [r['face_token'] for r in result['results'][:5]]
    except Exception as e:
        print(f"Face++ search failed: {str(e)}")
    return results

def save_api_results(image_path, google_results, facepp_results):
    try:
        conn = sqlite3.connect('api_results.db')
        cursor = conn.cursor()
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute('INSERT INTO api_results (image_path, google_results, facepp_results, timestamp) VALUES (?, ?, ?, ?)',
                      (image_path, json.dumps(google_results), json.dumps(facepp_results), timestamp))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Database save failed: {str(e)}")

def show_osint_popup(data):
    import tkinter as tk
    popup = tk.Toplevel()
    popup.title("OSINT Analysis Report")
    popup.geometry("800x600")
    popup.configure(bg="#1e1e1e")

    text = tk.Text(popup, wrap=tk.WORD, bg="#202d42", fg="white", font=("Consolas", 10))
    text.pack(expand=True, fill="both", padx=10, pady=10)

    if 'report_text' in data:
        text.insert(tk.END, data['report_text'])
    else:
        text.insert(tk.END, "No report data returned.")


def view_db_results():
    try:
        conn = sqlite3.connect('api_results.db')
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM api_results')
        rows = cursor.fetchall()
        popup = tk.Toplevel(bg="#202d42")
        popup.title("Database Results")
        popup.geometry("800x600+%d+%d" % (root.winfo_x() + 200, root.winfo_y() + 100))
        canvas = tk.Canvas(popup, bg="#202d42", highlightthickness=0)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(popup, command=canvas.yview)
        scrollbar.pack(side="right", fill="y")
        scroll_frame = ttk.Frame(canvas)
        scroll_win = canvas.create_window((0, 0), window=scroll_frame, anchor='nw')
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        row = 0
        for r in rows:
            ttk.Label(scroll_frame, text=f"Image: {r[0]}", font=('Arial', 12, 'bold')).grid(row=row, column=0, sticky='w', pady=5)
            row += 1
            ttk.Label(scroll_frame, text=f"Google Results: {r[1]}", font=('Arial', 12)).grid(row=row, column=0, sticky='w', pady=2)
            row += 1
            ttk.Label(scroll_frame, text=f"Face++ Results: {r[2]}", font=('Arial', 12)).grid(row=row, column=0, sticky='w', pady=2)
            row += 1
            ttk.Label(scroll_frame, text=f"Timestamp: {r[3]}", font=('Arial', 12)).grid(row=row, column=0, sticky='w', pady=2)
            row += 1
        conn.close()
    except Exception as e:
        message_queue.put(f"Failed to view database: {str(e)}")

def selectImage():
    global left_frame, img_label, img_read
    for wid in right_frame.winfo_children():
        wid.destroy()
    filetype = [("images", "*.jpg *.jpeg *.png")]
    path = filedialog.askopenfilename(title="Choose an image", filetypes=filetype)
    if len(path) > 0:
        img_read = cv2.imread(path)
        if img_read is None or img_read.size == 0:
            message_queue.put("Error: Failed to load selected image.")
            return
        img_read = cv2.resize(img_read, (460, 460), interpolation=cv2.INTER_AREA)
        img_size = (left_frame.winfo_width() - 40, left_frame.winfo_height() - 20)
        showImage(img_read, img_size)

def getPage2():
    global active_page, left_frame, right_frame, img_label, heading
    img_label = None
    active_page = 2
    pages[2].lift()
    basicPageSetup(2)
    heading.configure(text="Detect Criminal")
    right_frame.configure(text="Detected Criminals")
    btn_grid = ttk.Frame(left_frame)
    btn_grid.pack()
    ttk.Button(btn_grid, text="Select Image", command=selectImage).grid(row=0, column=0, padx=25, pady=25)
    recognize_btn = ttk.Button(btn_grid, text="Recognize", command=startRecognition, state='disabled')
    recognize_btn.grid(row=0, column=1, padx=25, pady=25)
    def enable_recognize():
        recognize_btn.config(state='normal')
    root.bind('<Configure>', lambda e: enable_recognize() if img_read is not None else None)

def check_liveness(frame, face_coord, eye_coords=[]):
    # Enhanced liveness check using eye detection and motion
    if not hasattr(check_liveness, 'prev_frame'):
        check_liveness.prev_frame = None
    if not eye_coords or len(eye_coords) < 2:  # Require at least two eyes
        return False
    if check_liveness.prev_frame is None:
        check_liveness.prev_frame = frame.copy()
        return True
    # Motion detection
    diff = cv2.absdiff(check_liveness.prev_frame, frame)
    motion_score = np.sum(diff) / (frame.shape[0] * frame.shape[1])
    # Eye presence check
    eye_count = len(eye_coords)
    check_liveness.prev_frame = frame.copy()
    return motion_score > 50.0 and eye_count >= 2

def analyze_face_attributes(frame, face_coord):
    try:
        from deepface import DeepFace
        x, y, w, h = face_coord
        face_roi = frame[y:y+h, x:x+w]
        attributes = DeepFace.analyze(face_roi, ['age', 'gender'], enforce_detection=False)
        if attributes and 'age' in attributes[0] and 'gender' in attributes[0]:
            return {'age': attributes[0]['age'], 'gender': attributes[0]['gender']}
        return {}
    except Exception as e:
        print(f"Attribute analysis failed: {str(e)}")
        return {}

def run_osint_analysis(image_path):
    osint_result = {"metadata": {}, "search_results": []}
    try:
        # Face++ Search
        facepp_matches = run_facepp_search(image_path)
        if facepp_matches:
            osint_result["metadata"]["Face++ Matches"] = len(facepp_matches)
            osint_result["search_results"].extend(facepp_matches)

        # PimEyes
        with open(image_path, 'rb') as image_file:
            pim_response = requests.post(
                "https://api.pimeyes.com/v1/search",
                files={"image": image_file},
                headers={"Authorization": f"Bearer {PIMEYES_API_KEY}"}
            )
            if pim_response.status_code == 200:
                data = pim_response.json()
                if data.get("matches"):
                    osint_result["metadata"]["PimEyes Matches"] = len(data["matches"])
                    osint_result["search_results"].extend([match["url"] for match in data["matches"][:5]])

        # SpiderFoot
        spiderfoot_url = "https://api.spiderfoot.net/v2/scan"
        spiderfoot_payload = {
            "target": name,
            "modules": ["sfp_dns", "sfp_google"],
            "key": SPIDERFOOT_API_KEY
        }
        spiderfoot_response = requests.post(spiderfoot_url, json=spiderfoot_payload)
        if spiderfoot_response.status_code == 200:
            data = spiderfoot_response.json()
            if data.get("result"):
                osint_result["metadata"]["SpiderFoot Findings"] = len(data["result"])
                osint_result["search_results"].extend([item["data"] for item in data["result"] if item.get("data")][:5])

        # Twint (commented out due to potential unavailability)
        # try:
        #     twint_output = subprocess.run(
        #         ["twint", "-u", name, "-o", "twint_results.txt", "--limit", "10"],
        #         capture_output=True, text=True
        #     )
        #     if os.path.exists("twint_results.txt"):
        #         with open("twint_results.txt", "r") as f:
        #             tweets = f.readlines()
        #             osint_result["metadata"]["Twitter Posts"] = len(tweets)
        #             osint_result["search_results"].extend(tweets[:5])
        # except Exception as e:
        #     print(f"Twint failed: {str(e)}")

    except Exception as e:
        print(f"OSINT search failed: {str(e)}")
    return osint_result

def run_webcam(model, names, img_size=(600, 500)):
    global webcam, img_label, left_frame, right_frame, capture_button
    max_attempts = 3
    for attempt in range(max_attempts):
        webcam = cv2.VideoCapture(0)
        if webcam.isOpened():
            break
        time.sleep(1)
    else:
        message_queue.put("Failed to access camera after multiple attempts. Check connection or permissions.")
        return
    old_recognized = []
    crims_found_labels = []
    if capture_button is None or not capture_button.winfo_exists():
        capture_button = ttk.Button(left_frame, text="Capture", command=capture_image)
        capture_button.pack(pady=10)
    def update_frame():
        global webcam
        if webcam is None or not webcam.isOpened():
            message_queue.put("Webcam disconnected or not accessible.")
            return
        ret, frame = webcam.read()
        if not ret or frame is None or frame.size == 0:
            message_queue.put("Failed to capture video frame. Camera may be disconnected.")
            webcam.release()
            return
        try:
            frame = cv2.flip(frame, 1)
            frame = cv2.resize(frame, img_size, interpolation=cv2.INTER_AREA)
            if frame is None or frame.size == 0:
                message_queue.put("Invalid frame received from webcam.")
                return
            face_coords, gray_frame, eye_coords = detect_faces(frame)
            if len(face_coords) > 0:
                frame, recognized = recognize_face(model, frame, gray_frame, face_coords, names, eye_coords)
                is_live = check_liveness(frame, face_coords[0], eye_coords[0] if eye_coords and len(eye_coords) > 0 else [])
                attributes = analyze_face_attributes(frame, face_coords[0]) if face_coords and len(face_coords) > 0 else {}
                recog_names = [item[0] for item in recognized]
                if recog_names != old_recognized:
                    for label in crims_found_labels:
                        label.destroy()
                    crims_found_labels.clear()
                    if recognized:
                        for i, crim in enumerate(recognized):
                            label_text = f"{crim[0]} (Confidence: {crim[1]:.2f})"
                            label_text += f"\nLiveness: {'Live' if is_live else 'Spoof Detected'}"
                            if attributes:
                                label_text += f"\nAge: {attributes.get('age', 'N/A')}, Gender: {attributes.get('gender', 'N/A')}"
                            label = ttk.Label(right_frame, text=label_text, foreground="white", background="orange", font=('Arial', 15, 'bold'))
                            label.pack(fill="x", padx=20, pady=10)
                            if label.winfo_exists():
                                label.bind("<Button-1>", lambda e, name=crim[0]: showCriminalProfile(name))
                            crims_found_labels.append(label)
                        first_match = recognized[0][0]
                        cv2.imwrite("temp_capture.png", frame)
                        osint_result = run_osint_search("temp_capture.png", first_match)
                        google_results = run_google_search("temp_capture.png")
                        facepp_results = run_facepp_analysis("temp_capture.png")
                        save_api_results("temp_capture.png", google_results, facepp_results)
                        osint_label = ttk.Label(right_frame, text="OSINT Results:", font=('Arial', 12, 'bold'), foreground="yellow")
                        osint_label.pack(padx=20, pady=5)
                        if osint_result["metadata"]:
                            for key, value in osint_result["metadata"].items():
                                ttk.Label(right_frame, text=f"{key}: {value}", font=('Arial', 12)).pack(padx=20, pady=2)
                        if osint_result["search_results"]:
                            for i, link in enumerate(osint_result["search_results"], 1):
                                ttk.Label(right_frame, text=f"{i}. {link}", font=('Arial', 12), foreground="blue", cursor="hand2").pack(padx=20, pady=2)
                        else:
                            ttk.Label(right_frame, text="No OSINT matches found.", font=('Arial', 12)).pack(padx=20, pady=2)
                        google_label = ttk.Label(right_frame, text="Google Results:", font=('Arial', 12, 'bold'), foreground="yellow")
                        google_label.pack(padx=20, pady=5)
                        if google_results:
                            for result in google_results[:3]:
                                ttk.Label(right_frame, text=f"URL: {result['link']}", font=('Arial', 12), foreground="blue", cursor="hand2").pack(padx=20, pady=2)
                        else:
                            ttk.Label(right_frame, text="No Google matches found.", font=('Arial', 12)).pack(padx=20, pady=2)
                        facepp_label = ttk.Label(right_frame, text="Face++ Analysis:", font=('Arial', 12, 'bold'), foreground="yellow")
                        facepp_label.pack(padx=20, pady=5)
                        if facepp_results:
                            for key, value in facepp_results.items():
                                ttk.Label(right_frame, text=f"{key}: {value}", font=('Arial', 12)).pack(padx=20, pady=2)
                        else:
                            ttk.Label(right_frame, text="No Face++ analysis available.", font=('Arial', 12)).pack(padx=20, pady=2)
                    else:
                        ttk.Label(right_frame, text="No criminals recognized.", font=('Arial', 12)).pack(padx=20, pady=5)
                    old_recognized.clear()
                    old_recognized.extend(recog_names)
            else:
                message_queue.put("No faces detected in the current frame.")
            showImage(frame, img_size)
        except Exception as e:
            message_queue.put(f"Error processing webcam frame: {str(e)}")
        if webcam and webcam.isOpened() and root.winfo_exists():
            root.after(33, update_frame)
        else:
            if webcam and webcam.isOpened():
                webcam.release()
            root.quit()
    update_frame()

def capture_image():
    global webcam, img_label, img_read
    if webcam is None or not webcam.isOpened():
        messagebox.showerror("Error", "Camera is not available.")
        return
    ret, frame = webcam.read()
    if ret and frame is not None and frame.size > 0:
        cv2.imwrite("temp_capture.png", frame)
        img_read = frame
        img_size = (left_frame.winfo_width() - 40, left_frame.winfo_height() - 20)
        showImage(frame, img_size)
        startRecognition()
    else:
        messagebox.showerror("Error", "Failed to capture a valid image.")

def videofile(path, model, names, img_size=(600,500)):
    global thread_event
    videofile = cv2.VideoCapture(path)
    if not videofile.isOpened():
        message_queue.put("Failed to open video file")
        return
    old_recognized = []
    crims_found_labels = []
    frame_count = 0
    try:
        while not thread_event.is_set():
            ret, frame = videofile.read()
            if not ret or frame is None or frame.size == 0:
                message_queue.put("Failed to read valid frame from video file")
                break
            frame = cv2.flip(frame, 1, 0)
            frame = cv2.resize(frame, img_size, interpolation=cv2.INTER_AREA)
            face_coords, gray_frame, eye_coords = detect_faces(frame)
            (frame, recognized) = recognize_face(model, frame, gray_frame, face_coords, names, eye_coords)
            recog_names = [item[0] for item in recognized]
            if recog_names != old_recognized:
                for i, crim in enumerate(recognized):
                    if i < len(crims_found_labels):
                        crims_found_labels[i].configure(text=crim[0])
                    else:
                        label = ttk.Label(right_frame, text=crim[0], foreground="white", background="orange", font=('Arial', 15, 'bold'))
                        label.pack(fill="x", padx=20, pady=10)
                        if label.winfo_exists():
                            label.bind("<Button-1>", lambda e, name=crim[0]: showCriminalProfile(name))
                        crims_found_labels.append(label)
                old_recognized = recog_names
            frame_count += 1
            if frame_count % 5 == 0:
                if left_frame.winfo_width() > 0 and left_frame.winfo_height() > 0:
                    showImage(frame, img_size)
            if cv2.waitKey(1) == 27:
                break
    except Exception as e:
        message_queue.put(f"Video processing failed: {str(e)}")
    finally:
        videofile.release()
        try:
            if left_frame.winfo_exists():
                left_frame.destroy()
        except tk.TclError:
            pass

def getPage3():
    global active_page, left_frame, right_frame, thread_event, heading
    active_page = 3
    pages[3].lift()
    basicPageSetup(3)
    heading.configure(text="Video Surveillance")
    right_frame.configure(text="Detected Criminals")
    btn_grid = ttk.Frame(left_frame)
    btn_grid.pack()
    ttk.Button(btn_grid, text="Upload Video", command=selectvideo).grid(row=0, column=0, padx=25, pady=25)

def selectvideo():
    global left_frame, img_label
    for wid in right_frame.winfo_children():
        wid.destroy()
    filetype = [("video", "*.mp4 *.mkv")]
    path = filedialog.askopenfilename(title="Choose a video", filetypes=filetype)
    if len(path) > 0:
        getPage4(path)

def getPage4(path):
    global active_page, left_frame, right_frame, thread_event, heading
    active_page = 3
    pages[3].lift()
    basicPageSetup(3)
    heading.configure(text="Video Surveillance")
    right_frame.configure(text="Detected Criminal")
    left_frame.configure()
    (model, names) = train_model()
    thread_event = threading.Event()
    thread = threading.Thread(target=videofile, args=(path, model, names))
    thread.start()

def getPage5():
    global active_page, left_frame, right_frame, heading, img_label, webcam, capture_button
    img_label = None
    if capture_button is not None and capture_button.winfo_exists():
        capture_button.destroy()
        capture_button = None
    active_page = 4
    pages[4].lift()
    basicPageSetup(4)
    heading.configure(text="Live Surveillance")
    right_frame.configure(text="Detected Criminals")
    left_frame.configure()
    (model, names) = train_model()
    run_webcam(model, names)

def getPage6():
    global active_page, left_frame, right_frame, heading, img_label, progress_bar
    img_label = None
    active_page = 5
    pages[5].lift()
    basicPageSetup(5)
    heading.configure(text="Image Search and Analysis")
    right_frame.configure(text="Search Results")
    btn_grid = ttk.Frame(left_frame)
    btn_grid.pack()
    ttk.Button(btn_grid, text="Upload Image", command=search_and_analyze_image).grid(row=0, column=0, padx=25, pady=25)

def search_and_analyze_image():
    global img_label, img_read, progress_bar
    for wid in right_frame.winfo_children():
        wid.destroy()
    filetype = [("images", "*.jpg *.jpeg *.png")]
    path = filedialog.askopenfilename(title="Choose an image", filetypes=filetype)
    if len(path) > 0:
        img_read = cv2.imread(path)
        if img_read is None or img_read.size == 0:
            message_queue.put("Error: Failed to load selected image.")
            return
        img_read = cv2.resize(img_read, (460, 460), interpolation=cv2.INTER_AREA)
        img_size = (left_frame.winfo_width() - 40, left_frame.winfo_height() - 200)
        showImage(img_read, img_size)
        if progress_bar:
            progress_bar.start()
        def analysis_task():
            try:
                google_results = run_google_search(path)
                facepp_results = run_facepp_analysis(path)
                save_api_results(path, google_results, facepp_results)
                result_text = "Google Reverse Image Search:\n"
                if google_results:
                    for result in google_results[:5]:
                        result_text += f"URL: {result['link']}\nTitle: {result.get('title', 'N/A')}\n\n"
                else:
                    result_text += "No Google matches found.\n\n"
                result_text += "Face++ Analysis:\n"
                if facepp_results:
                    for key, value in facepp_results.items():
                        result_text += f"{key}: {value}\n"
                else:
                    result_text += "No Face++ analysis available.\n"
                text_widget = tk.Text(right_frame, height=15, width=60, bg="#202d42", fg="white", font=('Arial', 12))
                text_widget.pack(padx=20, pady=10)
                scrollbar = ttk.Scrollbar(right_frame, command=text_widget.yview)
                scrollbar.pack(side="right", fill="y")
                text_widget.config(yscrollcommand=scrollbar.set)
                text_widget.insert(tk.END, result_text)
                text_widget.config(state='disabled')
            except Exception as e:
                message_queue.put(f"Search and analysis failed: {str(e)}")
            finally:
                if progress_bar:
                    root.after(0, lambda: progress_bar.stop())
        thread = threading.Thread(target=analysis_task)
        thread.start()

def find_widget_recursive(parent, widget_type, text=None):
    for child in parent.winfo_children():
        if isinstance(child, widget_type):
            if text is None or (hasattr(child, 'cget') and child.cget('text') == text):
                return child
        found = find_widget_recursive(child, widget_type, text)
        if found:
            return found
    return None

def on_configure(event, canvas, win):
    canvas.configure(scrollregion=canvas.bbox('all'))
    canvas.itemconfig(win, width=event.width)

def get_dashboard_stats():
    criminal_count = 0
    criminal_data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "criminal_data")
    if os.path.exists(criminal_data_dir):
        criminal_count = len([f for f in os.listdir(criminal_data_dir) if f.endswith('.json')])
    osint_hits = 0
    try:
        with open("osint_result.txt", "r", encoding="utf-8") as f:
            lines = f.readlines()
            for line in lines:
                if line.startswith("1. http"):
                    osint_hits += 1
    except FileNotFoundError:
        osint_hits = 0
    api_results_count = 0
    try:
        conn = sqlite3.connect('api_results.db')
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM api_results')
        api_results_count = cursor.fetchone()[0]
        conn.close()
    except:
        pass
    return criminal_count, osint_hits, api_results_count

# --- Enhanced Dashboard in home.py ---

# Update the dashboard section in home.py to show more informative stats
# like last recognized criminal, most frequent detections, OSINT summary, etc.
# This replaces the existing refresh_dashboard() implementation.

# --- Enhanced Dashboard in home.py ---

# Update the dashboard section in home.py to show more informative stats
# like last recognized criminal, most frequent detections, OSINT summary, etc.
# This replaces the existing refresh_dashboard() implementation.

def refresh_dashboard():
    global dashboard_labels
    for label in dashboard_labels:
        label.destroy()
    dashboard_labels.clear()

    project_dir = os.path.dirname(os.path.abspath(__file__))

    # 1. Registered Criminal Count
    criminal_data_dir = os.path.join(project_dir, "criminal_data")
    criminal_count = len([f for f in os.listdir(criminal_data_dir) if f.endswith('.json')]) if os.path.exists(criminal_data_dir) else 0

    # 2. Total Face Matches Found
    face_matches = 0
    try:
        conn = sqlite3.connect('api_results.db')
        cursor = conn.cursor()
        cursor.execute('SELECT facepp_results FROM api_results')
        rows = cursor.fetchall()
        for row in rows:
            data = json.loads(row[0])
            if data: face_matches += 1
        conn.close()
    except:
        pass

    # 3. Most Frequently Detected Criminal
    frequent_criminal = "N/A"
    detect_log_path = os.path.join(project_dir, "detections.json")
    if os.path.exists(detect_log_path):
        try:
            with open(detect_log_path, "r") as f:
                data = json.load(f)
            if data:
                sorted_data = sorted(data.items(), key=lambda x: x[1], reverse=True)
                frequent_criminal = f"{sorted_data[0][0]} ({sorted_data[0][1]} times)"
        except:
            frequent_criminal = "Error reading detections"

    # 4. Last Recognized Criminal
    last_recog = "N/A"
    activity_log_path = os.path.join(project_dir, "user_activity.txt")
    if os.path.exists(activity_log_path):
        try:
            with open(activity_log_path, "r") as f:
                lines = [line.strip() for line in f.readlines() if "Detected:" in line or "Recognized:" in line]
                if lines:
                    last_recog = lines[-1].replace("[✔] ", "")
        except:
            last_recog = "Could not read log"

    # 5. Total OSINT Domains Matched
    osint_domains = {}
    try:
        with open("osint_result.txt", "r", encoding="utf-8") as f:
            lines = f.readlines()
            for line in lines:
                if line.startswith("http") or line.startswith("1. http"):
                    domain = line.split("/")[2].strip()
                    osint_domains[domain] = osint_domains.get(domain, 0) + 1
    except:
        pass
    top_domains = sorted(osint_domains.items(), key=lambda x: x[1], reverse=True)[:3]
    top_domains_text = ", ".join([f"{d[0]} ({d[1]})" for d in top_domains]) if top_domains else "None"

    # Display Metrics
    metrics = [
        ("Registered Criminals", criminal_count),
        ("Total Face Matches Found", face_matches),
        ("Most Detected Criminal", frequent_criminal),
        ("Last Recognized", last_recog),
        ("Top OSINT Domains", top_domains_text)
    ]

    for label, value in metrics:
        dash_label = ttk.Label(dashboard_frame, text=f"{label}: {value}", font=('Arial', 15, 'bold'), foreground="yellow")
        dash_label.pack(anchor="w", padx=10, pady=5)
        dashboard_labels.append(dash_label)


# --- Vibrant and Professional Dashboard Layout with Real-Time Clock ---

# --- Vibrant and Professional Dashboard Layout with Real-Time Clock ---

# Main dashboard
dashboard_bg = "#1f2a38"  # deep navy
highlight = "#00c2ff"    # vibrant cyan
text_fg = "white"

pages[0].configure(bg=dashboard_bg)

# Function to update clock
def update_clock():
    now = time.strftime("%H:%M:%S | %d %b %Y")
    clock_label.config(text=f"🕒 {now}")
    clock_label.after(1000, update_clock)

# Title section
title_label = tk.Label(pages[0], text="Criminal Face Identification and OSINT Analysis System",
                       font=('Arial', 35, 'bold'), fg=highlight, bg=dashboard_bg)
title_label.pack(pady=(10, 0))

logo = tk.PhotoImage(file="logo.png")
tk.Label(pages[0], image=logo, bg=dashboard_bg).pack(pady=10)

# Clock in header
clock_label = tk.Label(pages[0], font=('Arial', 12, 'bold'), bg=dashboard_bg, fg=highlight)
clock_label.pack()
update_clock()

# Dashboard card
dashboard_frame = tk.LabelFrame(pages[0], text="Dashboard", labelanchor="n",
                                 bg=dashboard_bg, fg=highlight, font=('Arial', 12, 'bold'), bd=2, relief="groove")
dashboard_frame.pack(pady=20, padx=20, fill="x")
refresh_dashboard()

# Functional buttons section
btn_frame = tk.Frame(pages[0], bg=dashboard_bg)
btn_frame.pack()

button_styles = [
    ("📋 Register Criminal", getPage1),
    ("🧠 Detect Criminal", getPage2),
    ("🎥 Live Surveillance", getPage5),
    ("📼 Video Surveillance", getPage3),
    ("🖼️ Image Search", getPage6),
    ("📁 View Database", view_db_results)
]

for text, command in button_styles:
    btn = tk.Button(btn_frame, text=text, command=command, bg=highlight, fg="black",
                    font=('Arial', 12, 'bold'), activebackground="#009ec9", activeforeground="white",
                    width=20, height=2, bd=2, relief="ridge")
    btn.bind("<Enter>", lambda e, b=btn: b.config(bg="#00e0ff"))
    btn.bind("<Leave>", lambda e, b=btn: b.config(bg=highlight))
    btn.pack(side="left", padx=15, pady=20)

# Footer
footer = tk.Label(pages[0], text="© 2025 Criminal Intelligence Lab | AI-Driven Surveillance & OSINT Toolkit",
                   font=('Arial', 10), bg=dashboard_bg, fg="gray")
footer.pack(side="bottom", pady=10)

# Finalize view
pages[0].lift()
root.after(100, process_message_queue)
root.protocol("WM_DELETE_WINDOW", lambda: [webcam.release() if webcam and webcam.isOpened() else None, root.quit()])
root.mainloop()
# --- Final Polished Home Page with Logo Animation and About Button ---

# Add this at the end of your existing Page 0 (home/dashboard) setup:

def setup_homepage():
    pages[0].configure(bg="#1f2a38")

    # Title frame with logo and animated zoom effect
    title_frame = tk.Frame(pages[0], bg="#1f2a38")
    title_frame.pack(pady=10)

    logo_img = tk.PhotoImage(file="logo.png")
    logo_lbl = tk.Label(title_frame, image=logo_img, bg="#1f2a38")
    logo_lbl.image = logo_img
    logo_lbl.pack(side="left", padx=10)

    def on_enter_logo(e):
        logo_lbl.config(cursor="hand2")
        logo_lbl.after(0, lambda: logo_lbl.config(width=logo_img.width()+5))

    def on_leave_logo(e):
        logo_lbl.after(0, lambda: logo_lbl.config(width=logo_img.width()))

    logo_lbl.bind("<Enter>", on_enter_logo)
    logo_lbl.bind("<Leave>", on_leave_logo)

    title_lbl = tk.Label(title_frame, text="Criminal Face Identification and OSINT Analysis System",
                         font=('Arial', 35, 'bold'), fg="#00c2ff", bg="#1f2a38")
    title_lbl.pack(side="left")

    # Real-time clock
    clock_label = tk.Label(pages[0], font=('Arial', 12, 'bold'), bg="#1f2a38", fg="#00c2ff")
    clock_label.pack()

    def update_clock():
        now = time.strftime("%H:%M:%S | %d %b %Y")
        clock_label.config(text=f"🕒 {now}")
        clock_label.after(1000, update_clock)

    update_clock()

    # Dashboard section
    dashboard_frame = tk.LabelFrame(pages[0], text="Dashboard", labelanchor="n",
                                     bg="#1f2a38", fg="#00c2ff", font=('Arial', 12, 'bold'), bd=2, relief="groove")
    dashboard_frame.pack(pady=20, padx=20, fill="x")

    globals()['dashboard_frame'] = dashboard_frame
    globals()['dashboard_labels'] = []
    refresh_dashboard()

    # Navigation buttons
    btn_frame = tk.Frame(pages[0], bg="#1f2a38")
    btn_frame.pack(pady=20)

    button_styles = [
        ("📋 Register Criminal", getPage1),
        ("🧠 Detect Criminal", getPage2),
        ("🎥 Live Surveillance", getPage5),
        ("📼 Video Surveillance", getPage3),
        ("🖼️ Image Search", getPage6),
        ("📁 View Database", view_db_results)
    ]

    for text, command in button_styles:
        btn = tk.Button(btn_frame, text=text, command=command, bg="#00c2ff", fg="black",
                        font=('Arial', 12, 'bold'), activebackground="#009ec9", activeforeground="white",
                        width=20, height=2, bd=2, relief="ridge")
        btn.pack(side="left", padx=10, pady=10)
        btn.bind("<Enter>", lambda e, b=btn: b.config(bg="#00e0ff"))
        btn.bind("<Leave>", lambda e, b=btn: b.config(bg="#00c2ff"))

    # About button
    def show_about():
        messagebox.showinfo("About", "Developed by Pradeep Kumar\nCriminal Intelligence Lab 2025\nPowered by AI + OSINT Tools")

    about_btn = tk.Button(pages[0], text="❓ About", command=show_about,
                          font=('Arial', 10, 'bold'), bg="#273447", fg="white", width=12)
    about_btn.pack(pady=5)

    # Footer
    footer = tk.Label(pages[0], text="© 2025 Criminal Intelligence Lab | AI-Driven Surveillance & OSINT Toolkit",
                      font=('Arial', 10), bg="#1f2a38", fg="gray")
    footer.pack(side="bottom", pady=10)

    pages[0].lift()
    root.after(100, process_message_queue)
    root.protocol("WM_DELETE_WINDOW", lambda: [webcam.release() if webcam and webcam.isOpened() else None, root.quit()])

# Call this once when launching
setup_homepage()

