import os
import sys
import webbrowser
import threading
import time
import uvicorn

def get_base_dir():
    """Returns the correct base directory whether running as script or frozen exe."""
    if getattr(sys, 'frozen', False):
        # Running as PyInstaller bundle
        return os.path.dirname(sys.executable)
    else:
        # Running as normal script
        return os.path.dirname(os.path.abspath(__file__))

def open_browser():
    """Opens the default browser after a short delay to let the server start."""
    time.sleep(2)
    webbrowser.open("http://127.0.0.1")

if __name__ == "__main__":
    # Change working directory to the base directory
    base_dir = get_base_dir()
    os.chdir(base_dir)
    
    # Ensure required directories exist
    os.makedirs("uploads", exist_ok=True)
    os.makedirs("scratch", exist_ok=True)
    
    print("=" * 50)
    print("  HE THONG QUAN LY DU LIEU GCN")
    print("  Dang khoi dong may chu...")
    print("=" * 50)
    
    # Open browser in a separate thread
    threading.Thread(target=open_browser, daemon=True).start()
    
    print("  Trinh duyet se tu dong mo trong giay lat...")
    print("  Neu khong tu mo, hay truy cap: http://127.0.0.1")
    print("  De tat ung dung, dong cua so nay.")
    print("=" * 50)
    
    # Start the server (no reload when packaged)
    uvicorn.run("server.main:app", host="0.0.0.0", port=80, reload=False)
