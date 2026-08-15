import uvicorn

if __name__ == "__main__":
    print("Starting So hoa All in One Server...")
    print("Please open your browser and navigate to: http://localhost:80 (or your machine's LAN IP)")
    uvicorn.run("server.main:app", host="0.0.0.0", port=80, reload=True)
