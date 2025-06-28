import os

SCHOOL_SPRITE_DIR = "Sprites/school_uniform"
school_uniform_expressions = {
    "happy": "monika_happy(smile).png",
    "smile speaking": "monika_happy(speak).png",
    "side smile": "monika_happy(side-smile).png",
    "eyes close smile": "monika_happy(eyes-close).png",
    "pointing finger smile": "monika_happy(pointing-finger-smile).png",
    "side wink point smile": "monika_happy(side-wink-pointing-finger).png",
    "sad": "monika_sad.png",
    "crying": "monika_crying(speak).png",
    "sad smile": "monika_sad(smile).png",
    "neutral": "monika_neutral.png",
    "neutral speaking": "monika_neutral(speak).png",
    "side pissed": "monika_mad(side-pissed).png",
    "mad side speak": "monika_mad(side-speak).png",
    "horrified screams": "monika_Horrified(scream).png",
    "horrified speaking": "monika_Horrified(speak).png",
    "horrified concerned": "monika_Horrified(conerned).png",
    "serious": "monika_serious.png",
    "serious speaking": "monika_serious(speak).png",
    "serious pointing eyes close": "monika_serious(pointing-eyes-close).png",
    "serious pointing speaking eyes close": "monika_serious(speak-pointing-eyes-close).png",
    "concerned": "monika_conerned.png",
    "concerned speaking": "monika_conerned(speak).png",
    "embarrass": "monika_blush(eyes-close).png",
    "blushing with her eyes close": "monika_blush(eyes-close).png",
    "blushing side": "monika_blushing(side)-2.png",
    "nervous": "monika_nervous.png",
    "has a gun": "monika_with_gun.png",
    "oh shit she packing heat!": "monika_with_gun.png",
    "nervous speaking": "monika_nervous(speak).png",
    "nervous laughing": "monika_nervous(speak).png",
    "nervous laughing eyes close": "monika_nervous(laugh).png",
    "nervous speaking eyes close": "monika_nervous(laugh).png",
    "error": "monika_error-1.png",
    "glitching": "monika_error.gif",
    "thinking": "monika_thinking.png"
}

class ExpressionHandler:
    def __init__(self):
        self.valid = list(school_uniform_expressions.keys())

    async def classify(self, text, openai_client):
        prompt = (
            "Return ONLY one label from this list: \n"
            + ", ".join(self.valid) +
            "\nDescribe this message's emotion using one of the labels only."
        )

        response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": text}
            ],
            temperature=0
        )
        emotion = response.choices[0].message.content.strip().lower()
        return emotion if emotion in school_uniform_expressions else "neutral"

def get_expression_sprite(emotion):
    filename = school_uniform_expressions.get(emotion, "monika_neutral.png")
    path = os.path.join(SCHOOL_SPRITE_DIR, filename)
    return path if os.path.exists(path) else None