from fastapi import FastAPI

print(">>> Mythos booting")

app = FastAPI()

@app.get("/ping")
@app.get("/")
def ping():
    print(">>> Ping route hit")
    return {"message": "pong from ultra-minimal test"}
