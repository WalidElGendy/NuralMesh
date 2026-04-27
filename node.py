import ollama


def run_inference(prompt):
    response = ollama.chat(
        model="llama3",
        messages=[
            {
                "role": "user",
                "content": prompt,
            }
        ],
    )
    return response["message"]["content"]


print(run_inference("What is 2+2?"))
