from flask import Flask, request, render_template
from groq import Groq
from dotenv import load_dotenv
import os

load_dotenv()

app = Flask(__name__)

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# Chat history
messages = [
    {
        "role": "system",
        "content": "You are LifeLine AI, a helpful first aid and healthcare assistant. Give simple, safe advice and remind users to contact a doctor or emergency services for serious conditions."
    }
]


@app.route("/firstaid")
def firstaid():
    return render_template("firstaid.html")

@app.route("/healthtips")
def healthtips():
    return render_template("healthtips.html")

@app.route("/hospitals")
def hospitals():
    return render_template("hospitals.html")

@app.route("/about")
def about():
    return render_template("about.html")

@app.route("/", methods=["GET", "POST"])
def home():
    global messages

    if request.method == "POST":
        question = request.form["question"]

        messages.append({
            "role": "user",
            "content": question
        })

        try:
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=messages
            )

            answer = response.choices[0].message.content

        except Exception as e:
            answer = f"Error: {str(e)}"

        messages.append({
            "role": "assistant",
            "content": answer
        })

    return render_template("index.html", messages=messages)

if __name__ == "__main__":
    app.run(debug=True)