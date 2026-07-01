from fastapi import FastAPI

app = FastAPI()   # ← This line must exist at the top level (not inside a function)

@app.get("/")
async def root():
    return {"message": "Hello World"}
