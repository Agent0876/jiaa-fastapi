
"""
Entry point proxy for backward compatibility.
This allows running the app using `uvicorn main:app` from the project root.
"""
from app.main import app

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
