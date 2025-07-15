import os

SPRITE_DIR = "Sprites/DokiTubers"

class DokiGuy_SpritesManager:
    def __init__(self):
        self.DokiGuy_school_uniform = {
            "happy": "DokiGuy/school_uniform/Full_sprite/Mon1.png",
            "smile speaking": "DokiGuy/school_uniform/Full_sprite/Mon2.png",
            "side smile": "DokiGuy/school_uniform/Full_sprite/3aa.png",
            "eyes close smile": "DokiGuy/school_uniform/Full_sprite/Mon10.png",
            "eyes close smile speaking": "DokiGuy/school_uniform/Full_sprite/Mon11.png",
            "pointing finger smile": "DokiGuy/school_uniform/Full_sprite/Ika9.png",
            "side wink point smile": "DokiGuy/school_uniform/Full_sprite/happy(side-wink-pointing-finger).png",
            "sad": "DokiGuy/school_uniform/Full_sprite/Mon6.png",
            "crying": "DokiGuy/school_uniform/Full_sprite/Mon20.png",
            "sad smile": "DokiGuy/school_uniform/Full_sprite/Mon5.png",
            "neutral": "DokiGuy/school_uniform/Full_sprite/Mon3.png",
            "eyes close neutral": "DokiGuy/school_uniform/Full_sprite/Mon17.png",
            "neutral speaking": "DokiGuy/school_uniform/Full_sprite/Mon4.png",
            "eyes close neutral speaking": "DokiGuy/school_uniform/Full_sprite/Mon18.png",
            "side pissed": "DokiGuy/school_uniform/Full_sprite/3da.png",
            "mad side speak": "DokiGuy/school_uniform/Full_sprite/3bb.png",
            "horrified screams": "DokiGuy/school_uniform/Full_sprite/HorrifiedMonika8.png",
            "horrified speaking": "DokiGuy/school_uniform/Full_sprite/HorrifiedMonika5.png",
            "horrified babbling": "DokiGuy/school_uniform/Full_sprite/HorrifiedMonika6.png",
            "horrified surprised": "DokiGuy/school_uniform/Full_sprite/HorrifiedMonika4.png",
            "horrified no words": "DokiGuy/school_uniform/Full_sprite/HorrifiedMonika3.png",
            "horrified really surprised": "DokiGuy/school_uniform/Full_sprite/HorrifiedMonika2.png",
            "horrified": "DokiGuy/school_uniform/Full_sprite/HorrifiedMonika1.png",
            "horrified concerned": "DokiGuy/school_uniform/Full_sprite/HorrifiedMonika7.png",
            "serious": "DokiGuy/school_uniform/Full_sprite/Mon8.png",
            "serious pointing speaking": "DokiGuy/school_uniform/Full_sprite/Ika8.png",
            "serious pointing": "DokiGuy/school_uniform/Full_sprite/Ika7.png",
            "serious speaking": "DokiGuy/school_uniform/Full_sprite/Mon9.png",
            "serious pointing eyes close": "DokiGuy/school_uniform/Full_sprite/Ika15.png",
            "serious pointing speaking eyes close": "DokiGuy/school_uniform/Full_sprite/Ika16.png",
            "concerned": "DokiGuy/school_uniform/Full_sprite/Mon6.png",
            "concerned pointing": "DokiGuy/school_uniform/Full_sprite/Ika13.png",
            "concerned pointing speaking": "DokiGuy/school_uniform/Full_sprite/Ika14.png",
            "sad pointing smile looks away": "DokiGuy/school_uniform/Full_sprite/Ika12.png",
            "sad pointing smile": "DokiGuy/school_uniform/Full_sprite/Ika5.png",
            "sad pointing": "DokiGuy/school_uniform/Full_sprite/Ika6.png",
            "sad pointing smile speaking": "DokiGuy/school_uniform/Full_sprite/Ika11.png",
            "smile pointing speaking": "DokiGuy/school_uniform/Full_sprite/Ika10.png",
            "happy pointing speaking": "DokiGuy/school_uniform/Full_sprite/Ika2.png",
            "happy pointing": "DokiGuy/school_uniform/Full_sprite/Ika1.png",
            "neutral pointing speaking": "DokiGuy/school_uniform/Full_sprite/Ika4.png",
            "neutral pointing": "DokiGuy/school_uniform/Full_sprite/Ika3.png",
            "concerned speaking": "DokiGuy/school_uniform/Full_sprite/Mon7.png",
            "embarrass": "DokiGuy/school_uniform/Full_sprite/Mon19.png",
            "blushing with her eyes close": "DokiGuy/school_uniform/Full_sprite/Mon19.png",
            "blushing side": "DokiGuy/school_uniform/Full_sprite/3ca.png",
            "nervous": "DokiGuy/school_uniform/Full_sprite/Mon13.png",
            "really nervous": "DokiGuy/school_uniform/Full_sprite/Mon15.png",
            "has a gun": "DokiGuy/school_uniform/Full_sprite/Gun.png",
            "oh shit she packing heat!": "DokiGuy/school_uniform/Full_sprite/Gun.png",
            "threatened": "DokiGuy/school_uniform/Full_sprite/with_gun.png",
            "nervous speaking": "DokiGuy/school_uniform/Full_sprite/Mon16.png",
            "nervous laughing": "DokiGuy/school_uniform/Full_sprite/Mon14.png",
            "nervous laughing eyes close": "DokiGuy/school_uniform/Full_sprite/Mon12.png",
            "error": "DokiGuy/school_uniform/Full_sprite/G1.png",
            "glitching": "DokiGuy/school_uniform/Full_sprite/G5.gif",
            "thinking": "DokiGuy/school_uniform/Full_sprite/T1.png",
            "don't sure": "DokiGuy/school_uniform/Full_sprite/IDK.png",
            "Super": "DokiGuy/school_uniform/Full_sprite/Super_monika.png"
        }

        self.DokiGuy_casual_1 = {}

        self.DokiGuy_casual_1 = {}

class SteelAxleVII_SpritesManager:
    def __init__(self):
        self.SteelAxleVII_school_uniform = {}

        self.SteelAxleVII_casual_1 = {}

        self.SteelAxleVII_casual_2 = {}


class AfroZer0_SpritesManager:
    def __init__(self):
        
        self.AfroZer0_school_uniform = {}

        self.AfroZer0_casual_1 = {}

        self.AfroZer0_casual_2 = {}

        self.AfroZer0_Vigilante = {}

class Blugi_SpritesManager:
    def __init__(self):
        self.Blugi_school_uniform = {}

        self.Blugi_casual_1 = {}

        self.Blugi_casual_2 = {}


class DokiRaid_SpritesManager:
    def __init__(self):
        self.DokiRaid_school_uniform = {}

        self.DokiRaid_casual_1 = {}

        self.DokiRaid_casual_2 = {}


class FinnTDK_SpritesManager:
    def __init__(self):
        self.FinnTDK_school_uniform = {}

        self.FinnTDK_casual_1 = {}

        self.FinnTDK_casual_2 = {}


class Alyana_SpritesManager:
    def __init__(self):
        self.Alyana_school_uniform = {}

        self.Alyana_casual_1 = {}

        self.Alyana_casual_2 = {}


class Atazoth_SpritesManager:
    def __init__(self):
        self.Atazoth_school_uniform = {}

        self.Atazoth_casual_1 = {}

        self.Atazoth_casual_2 = {}


class Harveyedd_SpritesManager:
    def __init__(self):
        self.Harveyedd_school_uniform = {}

        self.Harveyedd_casual_1 = {}

        self.Harveyedd_casual_2 = {}


class DOKItheJay_SpritesManager:
    def __init__(self):
        self.DOKItheJay_school_uniform = {}

        self.DOKItheJay_casual_1 = {}

        self.DOKItheJay_casual_2 = {}


class Aliri_SpritesManager:
    def __init__(self):
        self.Aliri_casual_1 = {}

        self.Aliri_casual_glitch = {}


class Tbishy_SpritesManager:
    def __init__(self):
        self.Tbishy_school_uniform = {}

        self.Tbishy_casual_1 = {}

        self.Tbishy_casual_2 = {}


class YandereGaming_SpritesManager:
    def __init__(self):
        self.YandereGaming_school_uniform = {}

        self.YandereGaming_casual_1 = {}

        self.YandereGaming_casual_2 = {}


DOKITUBER_MANAGERS = {
    "DokiGuy": DokiGuy_SpritesManager(),
    "SteelAxleVII": SteelAxleVII_SpritesManager(),
    "AfroZer0": AfroZer0_SpritesManager(),
    "Blugi": Blugi_SpritesManager(),
    "DokiRaid": DokiRaid_SpritesManager(),
    "FinnTDK": FinnTDK_SpritesManager(),
    "Alyana": Alyana_SpritesManager(),
    "Atazoth": Atazoth_SpritesManager(),
    "Harveyedd": Harveyedd_SpritesManager(),
    "DOKItheJay": DOKItheJay_SpritesManager(),
    "Aliri": Aliri_SpritesManager(),
    "Tbishy": Tbishy_SpritesManager(),
    "Yandere Gaming": YandereGaming_SpritesManager(),
}

class ExpressionHandler:

    def get_dokituber_sprite(dokituber, expression, style="school"):
        manager = DOKITUBER_MANAGERS.get(dokituber)
        if not manager:
            return None

        if style == "school":
            return manager.school_uniform.get(expression)
        elif style == "casual":
            return manager.casual.get(expression)

        return None

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
        
    