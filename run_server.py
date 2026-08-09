import uvicorn

if __name__ == "__main__":
    print("Starting Enterprise Web Server...")
    print("Please open your browser and navigate to: http://127.0.0.1:8000")
    uvicorn.run("server.main:app", host="127.0.0.1", port=8000, reload=True)
