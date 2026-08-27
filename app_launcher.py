import os
import multiprocessing
import sys
import webbrowser
import threading
import time
import uvicorn
from dotenv import load_dotenv
from server.runtime_config import configure_server_runtime

load_dotenv()

def get_base_dir():
    """Returns the correct base directory whether running as script or frozen exe."""
    if getattr(sys, 'frozen', False):
        # Running as PyInstaller bundle
        return os.path.dirname(sys.executable)
    else:
        # Running as normal script
        return os.path.dirname(os.path.abspath(__file__))

def open_browser(host, port):
    """Opens the default browser after a short delay to let the server start."""
    time.sleep(2)
    # Nếu host là 0.0.0.0, mở trên localhost hoặc 127.0.0.1
    url_host = "127.0.0.1" if host == "0.0.0.0" else host
    url = f"http://{url_host}:{port}" if port != 80 else f"http://{url_host}"
    webbrowser.open(url)

def main():
    # Change working directory to the base directory
    base_dir = get_base_dir()
    os.chdir(base_dir)
    
    # Ensure required directories exist
    os.makedirs("uploads", exist_ok=True)
    os.makedirs("scratch", exist_ok=True)
    
    # Read environment variables
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "80"))
    runtime = configure_server_runtime()
    
    print("=" * 50)
    print("  SO HOA ALL IN ONE")
    print("  Dang khoi dong may chu...")
    print(f"  Workers: {runtime.workers}")
    print("=" * 50)
    
    # Open browser in a separate thread
    threading.Thread(target=open_browser, args=(host, port), daemon=True).start()
    
    print("  Trinh duyet se tu dong mo trong giay lat...")
    print(f"  Neu khong tu mo, hay truy cap: http://{'127.0.0.1' if host == '0.0.0.0' else host}:{port}")
    print("  De tat ung dung, dong cua so nay.")
    print("=" * 50)
    
    # Start the server (no reload when packaged)
    uvicorn.run(
        "server.main:app",
        host=host,
        port=port,
        reload=False,
        workers=runtime.workers,
    )


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
