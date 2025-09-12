# expression.py — fixed and more robust
import os, datetime, random, asyncio

SPRITE_DIR = "Sprites/user's"

def _today_date():
    """Return a date object representing today (useful for deterministic daily seeding)."""
    return datetime.date.today()

class User_SpritesManager:
    def __init__(self, sprite_dir=SPRITE_DIR):
        self.sprite_dir = sprite_dir

        # selected casual variant for the day (e.g. "casual 1")
        self._selected_casual_variant = None
        self._last_casual_date = None

        self.outfit_emotion_map = {
            "school uniform": ["happy", "smile speaking", "lean smile", "lean smile eyes close", "lean happy eyes close speaking", "lean happy speaking", "lean happy wink", "eyes close smile", "eyes close smile speaking", "pointing finger smile", "lean wink point smile", "sad", "crying", "sad smile", "neutral", "eyes close neutral", "neutral speaking", "eyes close neutral speaking", "pissed lean", "mad speaking lean", "mad leaning", "mad pitting face lean", "horrified screams", "horrified speaking", "horrified babbling", "horrified surprised", "horrified no words", "horrified really surprised", "horrified", "horrified concerned", "serious", "very serious", "disappointed", "serious pointing speaking", "serious pointing", "serious speaking", "serious pointing eyes close", "serious pointing speaking eyes close", "concerned", "concerned pointing", "concerned pointing speaking", "sad pointing smile looks away", "sad pointing smile", "sad pointing", "sad pointing smile speaking", "smile pointing speaking", "happy pointing speaking", "happy pointing", "neutral pointing speaking", "neutral pointing", "concerned speaking", "embarrass", "blushing with her eyes close", "smirk lean", "leaning kiss", "blushing leaning", "surprise speaking lean", "concerned speaking lean", "really...", "nervous", "really nervous", "nervous speaking", "nervous laughing", "nervous laughing eyes close", "thinking", "don't sure"],
            "casual 1": ["happy", "smile speaking", "lean smile", "lean smile eyes close", "lean happy eyes close speaking", "lean happy speaking", "lean happy wink", "eyes close smile", "eyes close smile speaking", "pointing finger smile", "sad", "crying", "sad smile", "neutral", "eyes close neutral", "neutral speaking", "eyes close neutral speaking", "pissed lean", "mad speaking lean", "mad leaning", "mad pitting face lean", "horrified screams", "horrified speaking", "horrified babbling", "horrified surprised", "horrified no words", "horrified really surprised", "horrified", "horrified concerned", "serious", "very serious", "disappointed", "serious pointing speaking", "serious pointing", "serious speaking", "serious pointing eyes close", "serious pointing speaking eyes close", "concerned", "concerned pointing", "concerned pointing speaking", "sad pointing smile looks away", "sad pointing smile", "sad pointing", "sad pointing smile speaking", "smile pointing speaking", "happy pointing speaking", "happy pointing", "neutral pointing speaking", "neutral pointing", "concerned speaking", "embarrass", "blushing with her eyes close", "leaning kiss", "blushing leaning", "surprise speaking lean", "concerned speaking lean", "really...", "nervous", "really nervous", "nervous speaking", "nervous laughing", "nervous laughing eyes close"],
            "casual 2": ["happy", "smile speaking", "eyes close smile", "eyes close smile speaking", "pointing finger smile", "sad", "crying", "sad smile", "neutral", "eyes close neutral", "neutral speaking", "eyes close neutral speaking", "horrified screams", "horrified speaking", "horrified babbling", "horrified surprised", "horrified no words", "horrified really surprised", "horrified", "horrified concerned", "serious", "very serious", "disappointed", "serious pointing speaking", "serious pointing", "serious speaking", "serious pointing eyes close", "serious pointing speaking eyes close", "concerned", "concerned pointing", "concerned pointing speaking", "sad pointing smile looks away", "sad pointing smile", "sad pointing", "sad pointing smile speaking", "smile pointing speaking", "happy pointing speaking", "happy pointing", "neutral pointing speaking", "neutral pointing", "concerned speaking", "embarrass", "blushing with her eyes close", "nervous", "really nervous", "nervous speaking", "nervous laughing", "nervous laughing eyes close"],
            "casual 3": ["happy", "smile speaking", "eyes close smile", "eyes close smile speaking", "pointing finger smile", "sad", "crying", "sad smile", "neutral", "eyes close neutral", "neutral speaking", "eyes close neutral speaking", "horrified screams", "horrified speaking", "horrified babbling", "horrified surprised", "horrified no words", "horrified really surprised", "horrified", "horrified concerned", "serious", "very serious", "disappointed", "serious pointing speaking", "serious pointing", "serious speaking", "serious pointing eyes close", "serious pointing speaking eyes close", "concerned", "concerned pointing", "concerned pointing speaking", "sad pointing smile looks away", "sad pointing smile", "sad pointing", "sad pointing smile speaking", "smile pointing speaking", "happy pointing speaking", "happy pointing", "neutral pointing speaking", "neutral pointing", "concerned speaking", "embarrass", "blushing with her eyes close", "nervous", "really nervous", "nervous speaking", "nervous laughing", "nervous laughing eyes close"],
            "special": ["oh shit she packing heat!", "threatened", "gauntlet"],
            "bug": ["error", "glitching"],
            "white summer dress": ["happy", "smile speaking", "eyes close smile", "eyes close smile speaking", "pointing finger smile", "sad", "crying", "sad smile", "neutral", "eyes close neutral", "neutral speaking", "eyes close neutral speaking", "horrified screams", "horrified speaking", "horrified babbling", "horrified surprised", "horrified no words", "horrified really surprised", "horrified", "horrified concerned", "serious", "very serious", "disappointed", "serious pointing speaking", "serious pointing", "serious speaking", "serious pointing eyes close", "serious pointing speaking eyes close", "concerned", "concerned pointing", "concerned pointing speaking", "sad pointing smile looks away", "sad pointing smile", "sad pointing", "sad pointing smile speaking", "smile pointing speaking", "happy pointing speaking", "happy pointing", "neutral pointing speaking", "neutral pointing", "concerned speaking", "embarrass", "blushing with her eyes close", "nervous", "really nervous", "nervous speaking", "nervous laughing", "nervous laughing eyes close"],
            "hoodie": ["happy", "smile speaking", "eyes close smile", "eyes close smile speaking", "pointing finger smile", "sad", "crying", "sad smile", "neutral", "eyes close neutral", "neutral speaking", "eyes close neutral speaking", "horrified screams", "horrified speaking", "horrified babbling", "horrified surprised", "horrified no words", "horrified really surprised", "horrified", "horrified concerned", "serious", "very serious", "disappointed", "serious pointing speaking", "serious pointing", "serious speaking", "serious pointing eyes close", "serious pointing speaking eyes close", "concerned", "concerned pointing", "concerned pointing speaking", "sad pointing smile looks away", "sad pointing smile", "sad pointing", "sad pointing smile speaking", "smile pointing speaking", "happy pointing speaking", "happy pointing", "neutral pointing speaking", "neutral pointing", "concerned speaking", "embarrass", "blushing with her eyes close", "nervous", "really nervous", "nervous speaking", "nervous laughing", "nervous laughing eyes close"],
            "pajamas": ["happy", "smile speaking", "lean smile", "lean smile eyes close", "lean happy eyes close speaking", "lean happy speaking", "lean happy wink", "eyes close smile", "eyes close smile speaking", "pointing finger smile", "lean wink point smile", "sad", "crying", "sad smile", "neutral", "eyes close neutral", "neutral speaking", "eyes close neutral speaking", "pissed lean", "mad speaking lean", "mad leaning", "mad pitting face lean", "horrified screams", "horrified speaking", "horrified babbling", "horrified surprised", "horrified no words", "horrified really surprised", "horrified", "horrified concerned", "serious", "very serious", "disappointed", "serious pointing speaking", "serious pointing", "serious speaking", "serious pointing eyes close", "serious pointing speaking eyes close", "concerned", "concerned pointing", "concerned pointing speaking", "sad pointing smile looks away", "sad pointing smile", "sad pointing", "sad pointing smile speaking", "smile pointing speaking", "happy pointing speaking", "happy pointing", "neutral pointing speaking", "neutral pointing", "concerned speaking", "embarrass", "blushing with her eyes close", "smirk lean", "leaning kiss", "blushing leaning", "surprise speaking lean", "concerned speaking lean", "really...", "nervous", "really nervous", "nervous speaking", "nervous laughing", "nervous laughing eyes close"],
            "green dress": ["happy", "smile speaking", "lean smile", "lean smile eyes close", "lean happy eyes close speaking", "lean happy speaking", "lean happy wink", "eyes close smile", "eyes close smile speaking", "pointing finger smile", "lean wink point smile", "sad", "crying", "sad smile", "neutral", "eyes close neutral", "neutral speaking", "eyes close neutral speaking", "pissed lean", "mad speaking lean", "mad leaning", "mad pitting face lean", "horrified screams", "horrified speaking", "horrified babbling", "horrified surprised", "horrified no words", "horrified really surprised", "horrified", "horrified concerned", "serious", "very serious", "disappointed", "serious pointing speaking", "serious pointing", "serious speaking", "serious pointing eyes close", "serious pointing speaking eyes close", "concerned", "concerned pointing", "concerned pointing speaking", "sad pointing smile looks away", "sad pointing smile", "sad pointing", "sad pointing smile speaking", "smile pointing speaking", "happy pointing speaking", "happy pointing", "neutral pointing speaking", "neutral pointing", "concerned speaking", "embarrass", "blushing with her eyes close", "smirk lean", "leaning kiss", "blushing leaning", "surprise speaking lean", "concerned speaking lean", "really...", "nervous", "really nervous", "nervous speaking", "nervous laughing", "nervous laughing eyes close"]
            # add more outfits with their allowed emotions
        }

        # The raw mapping of outfit -> emotion -> path.
        # (Keeps the same structure as before — paths will be normalized in _load_sprites.)
        self.EXPRESSION_SPRITES = {
            "school uniform": {
                "happy": f"{self.sprite_dir}/school_uniform/Mon1.png",
                "smile speaking": f"{self.sprite_dir}/school_uniform/Mon2.png",
                "lean smile": f"{self.sprite_dir}/school_uniform/3aa.png",
                "lean smile eyes close": f"{self.sprite_dir}/school_uniform/3ab.png",
                "lean happy eyes close speaking": f"{self.sprite_dir}/school_uniform/3ac.png",
                "lean happy speaking": f"{self.sprite_dir}/school_uniform/3ad.png",
                "lean happy wink": f"{self.sprite_dir}/school_uniform/3ae.png",
                "eyes close smile": f"{self.sprite_dir}/school_uniform/Mon10.png",
                "eyes close smile speaking": f"{self.sprite_dir}/school_uniform/Mon11.png",
                "pointing finger smile": f"{self.sprite_dir}/school_uniform/Ika9.png",
                "lean wink point smile": f"{self.sprite_dir}/school_uniform/3Ika.png",
                "sad": f"{self.sprite_dir}/school_uniform/Mon6.png",
                "crying": f"{self.sprite_dir}/school_uniform/Mon20.png",
                "sad smile": f"{self.sprite_dir}/school_uniform/Mon5.png",
                "neutral": f"{self.sprite_dir}/school_uniform/Mon3.png",
                "eyes close neutral": f"{self.sprite_dir}/school_uniform/Mon17.png",
                "neutral speaking": f"{self.sprite_dir}/school_uniform/Mon4.png",
                "eyes close neutral speaking": f"{self.sprite_dir}/school_uniform/Mon18.png",
                "pissed lean": f"{self.sprite_dir}/school_uniform/3bd.png",
                "mad speaking lean": f"{self.sprite_dir}/school_uniform/3ba.png",
                "mad leaning": f"{self.sprite_dir}/school_uniform/3bb.png",
                "mad pitting face lean": f"{self.sprite_dir}/school_uniform/3bc.png",
                "horrified screams": f"{self.sprite_dir}/school_uniform/HorrifiedMonika8.png",
                "horrified speaking": f"{self.sprite_dir}/school_uniform/HorrifiedMonika5.png",
                "horrified babbling": f"{self.sprite_dir}/school_uniform/HorrifiedMonika6.png",
                "horrified surprised": f"{self.sprite_dir}/school_uniform/HorrifiedMonika4.png",
                "horrified no words": f"{self.sprite_dir}/school_uniform/HorrifiedMonika3.png",
                "horrified really surprised": f"{self.sprite_dir}/school_uniform/HorrifiedMonika2.png",
                "horrified": f"{self.sprite_dir}/school_uniform/HorrifiedMonika1.png",
                "horrified concerned": f"{self.sprite_dir}/school_uniform/HorrifiedMonika7.png",
                "serious": f"{self.sprite_dir}/school_uniform/Mon8.png",
                "very serious": f"{self.sprite_dir}/school_uniform/Mon21.png",
                "disappointed": f"{self.sprite_dir}/school_uniform/Mon21.png",
                "serious pointing speaking": f"{self.sprite_dir}/school_uniform/Ika8.png",
                "serious pointing": f"{self.sprite_dir}/school_uniform/Ika7.png",
                "serious speaking": f"{self.sprite_dir}/school_uniform/Mon9.png",
                "serious pointing eyes close": f"{self.sprite_dir}/school_uniform/Ika15.png",
                "serious pointing speaking eyes close": f"{self.sprite_dir}/school_uniform/Ika16.png",
                "concerned": f"{self.sprite_dir}/school_uniform/Mon6.png",
                "concerned pointing": f"{self.sprite_dir}/school_uniform/Ika13.png",
                "concerned pointing speaking": f"{self.sprite_dir}/school_uniform/Ika14.png",
                "sad pointing smile looks away": f"{self.sprite_dir}/school_uniform/Ika12.png",
                "sad pointing smile": f"{self.sprite_dir}/school_uniform/Ika5.png",
                "sad pointing": f"{self.sprite_dir}/school_uniform/Ika6.png",
                "sad pointing smile speaking": f"{self.sprite_dir}/school_uniform/Ika11.png",
                "smile pointing speaking": f"{self.sprite_dir}/school_uniform/Ika10.png",
                "happy pointing speaking": f"{self.sprite_dir}/school_uniform/Ika2.png",
                "happy pointing": f"{self.sprite_dir}/school_uniform/Ika1.png",
                "neutral pointing speaking": f"{self.sprite_dir}/school_uniform/Ika4.png",
                "neutral pointing": f"{self.sprite_dir}/school_uniform/Ika3.png",
                "concerned speaking": f"{self.sprite_dir}/school_uniform/Mon7.png",
                "embarrass": f"{self.sprite_dir}/school_uniform/Mon19.png",
                "blushing with her eyes close": f"{self.sprite_dir}/school_uniform/Mon19.png",
                "smirk lean": f"{self.sprite_dir}/school_uniform/3ca.png",
                "leaning kiss": f"{self.sprite_dir}/school_uniform/3cb.png",
                "blushing leaning": f"{self.sprite_dir}/school_uniform/3cc.png",
                "surprise speaking lean": f"{self.sprite_dir}/school_uniform/3da.png",
                "concerned speaking lean": f"{self.sprite_dir}/school_uniform/3ea.png",
                "really...": f"{self.sprite_dir}/pajamas/3fa.png",
                "nervous": f"{self.sprite_dir}/school_uniform/Mon13.png",
                "really nervous": f"{self.sprite_dir}/school_uniform/Mon15.png",
                "nervous speaking": f"{self.sprite_dir}/school_uniform/Mon16.png",
                "nervous laughing": f"{self.sprite_dir}/school_uniform/Mon14.png",
                "nervous laughing eyes close": f"{self.sprite_dir}/school_uniform/Mon12.png",
                "thinking": f"{self.sprite_dir}/school_uniform/T1.png",
                "don't sure": f"{self.sprite_dir}/school_uniform/IDK.png",
            },
            "bug": {
                "error": f"{self.sprite_dir}/bug/G1.png",
                "glitching": f"{self.sprite_dir}/bug/G5.gif"
            },
            "special": {
                "oh shit she packing heat!": f"{self.sprite_dir}/special/Gun.png",
                "threatened": f"{self.sprite_dir}/special/Gun.png",
                "gauntlet": f"{self.sprite_dir}/special/IG6S.webp"
            },
            "casual 1": {
                "happy": f"{self.sprite_dir}/casual1/Mon1.png",
                "smile speaking": f"{self.sprite_dir}/casual1/Mon2.png",
                "lean smile": f"{self.sprite_dir}/casual1/3aa.png",
                "lean smile eyes close": f"{self.sprite_dir}/casual1/3ab.png",
                "lean happy eyes close speaking": f"{self.sprite_dir}/casual1/3ac.png",
                "lean happy speaking": f"{self.sprite_dir}/casual1/3ad.png",
                "lean happy wink": f"{self.sprite_dir}/casual1/3ae.png",
                "eyes close smile": f"{self.sprite_dir}/casual1/Mon10.png",
                "eyes close smile speaking": f"{self.sprite_dir}/casual1/Mon11.png",
                "pointing finger smile": f"{self.sprite_dir}/casual1/Ika9.png",
                "sad": f"{self.sprite_dir}/casual1/Mon6.png",
                "crying": f"{self.sprite_dir}/casual1/Mon20.png",
                "sad smile": f"{self.sprite_dir}/casual1/Mon5.png",
                "neutral": f"{self.sprite_dir}/casual1/Mon3.png",
                "eyes close neutral": f"{self.sprite_dir}/casual1/Mon17.png",
                "neutral speaking": f"{self.sprite_dir}/casual1/Mon4.png",
                "eyes close neutral speaking": f"{self.sprite_dir}/casual1/Mon18.png",
                "pissed lean": f"{self.sprite_dir}/casual1/3bd.png",
                "mad speaking lean": f"{self.sprite_dir}/casual1/3ba.png",
                "mad leaning": f"{self.sprite_dir}/casual1/3bb.png",
                "mad pitting face lean": f"{self.sprite_dir}/casual1/3bc.png",
                "horrified screams": f"{self.sprite_dir}/casual1/HorrifiedMonika8.png",
                "horrified speaking": f"{self.sprite_dir}/casual1/HorrifiedMonika5.png",
                "horrified babbling": f"{self.sprite_dir}/casual1/HorrifiedMonika6.png",
                "horrified surprised": f"{self.sprite_dir}/casual1/HorrifiedMonika4.png",
                "horrified no words": f"{self.sprite_dir}/casual1/HorrifiedMonika3.png",
                "horrified really surprised": f"{self.sprite_dir}/casual1/HorrifiedMonika2.png",
                "horrified": f"{self.sprite_dir}/casual1/HorrifiedMonika1.png",
                "horrified concerned": f"{self.sprite_dir}/casual1/HorrifiedMonika7.png",
                "serious": f"{self.sprite_dir}/casual1/Mon8.png",
                "very serious": f"{self.sprite_dir}/casual1/Mon21.png",
                "disappointed": f"{self.sprite_dir}/casual1/Mon21.png",
                "serious pointing speaking": f"{self.sprite_dir}/casual1/Ika8.png",
                "serious pointing": f"{self.sprite_dir}/casual1/Ika7.png",
                "serious speaking": f"{self.sprite_dir}/casual1/Mon9.png",
                "serious pointing eyes close": f"{self.sprite_dir}/casual1/Ika15.png",
                "serious pointing speaking eyes close": f"{self.sprite_dir}/casual1/Ika16.png",
                "concerned": f"{self.sprite_dir}/casual1/Mon6.png",
                "concerned pointing": f"{self.sprite_dir}/casual1/Ika13.png",
                "concerned pointing speaking": f"{self.sprite_dir}/casual1/Ika14.png",
                "sad pointing smile looks away": f"{self.sprite_dir}/casual1/Ika12.png",
                "sad pointing smile": f"{self.sprite_dir}/casual1/Ika5.png",
                "sad pointing": f"{self.sprite_dir}/casual1/Ika6.png",
                "sad pointing smile speaking": f"{self.sprite_dir}/casual1/Ika11.png",
                "smile pointing speaking": f"{self.sprite_dir}/casual1/Ika10.png",
                "happy pointing speaking": f"{self.sprite_dir}/casual1/Ika2.png",
                "happy pointing": f"{self.sprite_dir}/casual1/Ika1.png",
                "neutral pointing speaking": f"{self.sprite_dir}/casual1/Ika4.png",
                "neutral pointing": f"{self.sprite_dir}/casual1/Ika3.png",
                "concerned speaking": f"{self.sprite_dir}/casual1/Mon7.png",
                "embarrass": f"{self.sprite_dir}/casual1/Mon19.png",
                "blushing with her eyes close": f"{self.sprite_dir}/casual1/Mon19.png",
                "leaning kiss": f"{self.sprite_dir}/casual1/3cb.png",
                "blushing leaning": f"{self.sprite_dir}/casual1/3cc.png",
                "surprise speaking lean": f"{self.sprite_dir}/casual1/3da.png",
                "concerned speaking lean": f"{self.sprite_dir}/casual1/3ea.png",
                "really...": f"{self.sprite_dir}/pajamas/3fa.png",
                "nervous": f"{self.sprite_dir}/casual1/Mon13.png",
                "really nervous": f"{self.sprite_dir}/casual1/Mon15.png",
                "nervous speaking": f"{self.sprite_dir}/casual1/Mon16.png",
                "nervous laughing": f"{self.sprite_dir}/casual1/Mon14.png",
                "nervous laughing eyes close": f"{self.sprite_dir}/casual1/Mon12.png"
            },
            "casual 2": {
                "happy": f"{self.sprite_dir}/casual2/Mon1.png",
                "smile speaking": f"{self.sprite_dir}/casual2/Mon2.png",
                "eyes close smile": f"{self.sprite_dir}/casual2/Mon10.png",
                "eyes close smile speaking": f"{self.sprite_dir}/casual2/Mon11.png",
                "pointing finger smile": f"{self.sprite_dir}/casual2/Ika9.png",
                "sad": f"{self.sprite_dir}/casual2/Mon6.png",
                "crying": f"{self.sprite_dir}/casual2/Mon20.png",
                "sad smile": f"{self.sprite_dir}/casual2/Mon5.png",
                "neutral": f"{self.sprite_dir}/casual2/Mon3.png",
                "eyes close neutral": f"{self.sprite_dir}/casual2/Mon17.png",
                "neutral speaking": f"{self.sprite_dir}/casual2/Mon4.png",
                "eyes close neutral speaking": f"{self.sprite_dir}/casual2/Mon18.png",
                "horrified screams": f"{self.sprite_dir}/casual2/HorrifiedMonika8.png",
                "horrified speaking": f"{self.sprite_dir}/casual2/HorrifiedMonika5.png",
                "horrified babbling": f"{self.sprite_dir}/casual2/HorrifiedMonika6.png",
                "horrified surprised": f"{self.sprite_dir}/casual2/HorrifiedMonika4.png",
                "horrified no words": f"{self.sprite_dir}/casual2/HorrifiedMonika3.png",
                "horrified really surprised": f"{self.sprite_dir}/casual2/HorrifiedMonika2.png",
                "horrified": f"{self.sprite_dir}/casual2/HorrifiedMonika1.png",
                "horrified concerned": f"{self.sprite_dir}/casual2/HorrifiedMonika7.png",
                "serious": f"{self.sprite_dir}/casual2/Mon8.png",
                "very serious": f"{self.sprite_dir}/casual2/Mon21.png",
                "disappointed": f"{self.sprite_dir}/casual2/Mon21.png",
                "serious pointing speaking": f"{self.sprite_dir}/casual2/Ika8.png",
                "serious pointing": f"{self.sprite_dir}/casual2/Ika7.png",
                "serious speaking": f"{self.sprite_dir}/casual2/Mon9.png",
                "serious pointing eyes close": f"{self.sprite_dir}/casual2/Ika15.png",
                "serious pointing speaking eyes close": f"{self.sprite_dir}/casual2/Ika16.png",
                "concerned": f"{self.sprite_dir}/casual2/Mon6.png",
                "concerned pointing": f"{self.sprite_dir}/casual2/Ika13.png",
                "concerned pointing speaking": f"{self.sprite_dir}/casual2/Ika14.png",
                "sad pointing smile looks away": f"{self.sprite_dir}/casual2/Ika12.png",
                "sad pointing smile": f"{self.sprite_dir}/casual2/Ika5.png",
                "sad pointing": f"{self.sprite_dir}/casual2/Ika6.png",
                "sad pointing smile speaking": f"{self.sprite_dir}/casual2/Ika11.png",
                "smile pointing speaking": f"{self.sprite_dir}/casual2/Ika10.png",
                "happy pointing speaking": f"{self.sprite_dir}/casual2/Ika2.png",
                "happy pointing": f"{self.sprite_dir}/casual2/Ika1.png",
                "neutral pointing speaking": f"{self.sprite_dir}/casual2/Ika4.png",
                "neutral pointing": f"{self.sprite_dir}/casual2/Ika3.png",
                "concerned speaking": f"{self.sprite_dir}/casual2/Mon7.png",
                "embarrass": f"{self.sprite_dir}/casual2/Mon19.png",
                "blushing with her eyes close": f"{self.sprite_dir}/casual2/Mon19.png",
                "nervous": f"{self.sprite_dir}/casual2/Mon13.png",
                "really nervous": f"{self.sprite_dir}/casual2/Mon15.png",
                "nervous speaking": f"{self.sprite_dir}/casual2/Mon16.png",
                "nervous laughing": f"{self.sprite_dir}/casual2/Mon14.png",
                "nervous laughing eyes close": f"{self.sprite_dir}/casual2/Mon12.png",
            },
            "casual 3": {
                "happy": f"{self.sprite_dir}/casual3/Mon1.png",
                "smile speaking": f"{self.sprite_dir}/casual3/Mon2.png",
                "eyes close smile": f"{self.sprite_dir}/casual3/Mon10.png",
                "eyes close smile speaking": f"{self.sprite_dir}/casual3/Mon11.png",
                "pointing finger smile": f"{self.sprite_dir}/casual3/Ika9.png",
                "sad": f"{self.sprite_dir}/casual3/Mon6.png",
                "crying": f"{self.sprite_dir}/casual3/Mon20.png",
                "sad smile": f"{self.sprite_dir}/casual3/Mon5.png",
                "neutral": f"{self.sprite_dir}/casual3/Mon3.png",
                "eyes close neutral": f"{self.sprite_dir}/casual3/Mon17.png",
                "neutral speaking": f"{self.sprite_dir}/casual3/Mon4.png",
                "eyes close neutral speaking": f"{self.sprite_dir}/casual3/Mon18.png",
                "horrified screams": f"{self.sprite_dir}/casual3/HorrifiedMonika8.png",
                "horrified speaking": f"{self.sprite_dir}/casual3/HorrifiedMonika5.png",
                "horrified babbling": f"{self.sprite_dir}/casual3/HorrifiedMonika6.png",
                "horrified surprised": f"{self.sprite_dir}/casual3/HorrifiedMonika4.png",
                "horrified no words": f"{self.sprite_dir}/casual3/HorrifiedMonika3.png",
                "horrified really surprised": f"{self.sprite_dir}/casual3/HorrifiedMonika2.png",
                "horrified": f"{self.sprite_dir}/casual3/HorrifiedMonika1.png",
                "horrified concerned": f"{self.sprite_dir}/casual3/HorrifiedMonika7.png",
                "serious": f"{self.sprite_dir}/casual3/Mon8.png",
                "very serious": f"{self.sprite_dir}/casual3/Mon21.png",
                "disappointed": f"{self.sprite_dir}/casual3/Mon21.png",
                "serious pointing speaking": f"{self.sprite_dir}/casual3/Ika8.png",
                "serious pointing": f"{self.sprite_dir}/casual3/Ika7.png",
                "serious speaking": f"{self.sprite_dir}/casual3/Mon9.png",
                "serious pointing eyes close": f"{self.sprite_dir}/casual3/Ika15.png",
                "serious pointing speaking eyes close": f"{self.sprite_dir}/casual3/Ika16.png",
                "concerned": f"{self.sprite_dir}/casual3/Mon6.png",
                "concerned pointing": f"{self.sprite_dir}/casual3/Ika13.png",
                "concerned pointing speaking": f"{self.sprite_dir}/casual3/Ika14.png",
                "sad pointing smile looks away": f"{self.sprite_dir}/casual3/Ika12.png",
                "sad pointing smile": f"{self.sprite_dir}/casual3/Ika5.png",
                "sad pointing": f"{self.sprite_dir}/casual3/Ika6.png",
                "sad pointing smile speaking": f"{self.sprite_dir}/casual3/Ika11.png",
                "smile pointing speaking": f"{self.sprite_dir}/casual3/Ika10.png",
                "happy pointing speaking": f"{self.sprite_dir}/casual3/Ika2.png",
                "happy pointing": f"{self.sprite_dir}/casual3/Ika1.png",
                "neutral pointing speaking": f"{self.sprite_dir}/casual3/Ika4.png",
                "neutral pointing": f"{self.sprite_dir}/casual3/Ika3.png",
                "concerned speaking": f"{self.sprite_dir}/casual3/Mon7.png",
                "embarrass": f"{self.sprite_dir}/casual3/Mon19.png",
                "blushing with her eyes close": f"{self.sprite_dir}/casual3/Mon19.png",
                "nervous": f"{self.sprite_dir}/casual3/Mon13.png",
                "really nervous": f"{self.sprite_dir}/casual3/Mon15.png",
                "nervous speaking": f"{self.sprite_dir}/casual3/Mon16.png",
                "nervous laughing": f"{self.sprite_dir}/casual3/Mon14.png",
                "nervous laughing eyes close": f"{self.sprite_dir}/casual3/Mon12.png",
            },
            "hoodie": {
                "happy": f"{self.sprite_dir}/hoodie/Mon1.png",
                "smile speaking": f"{self.sprite_dir}/hoodie/Mon2.png",
                "eyes close smile": f"{self.sprite_dir}/hoodie/Mon10.png",
                "eyes close smile speaking": f"{self.sprite_dir}/hoodie/Mon11.png",
                "pointing finger smile": f"{self.sprite_dir}/hoodie/Ika9.png",
                "sad": f"{self.sprite_dir}/hoodie/Mon6.png",
                "crying": f"{self.sprite_dir}/hoodie/Mon20.png",
                "sad smile": f"{self.sprite_dir}/hoodie/Mon5.png",
                "neutral": f"{self.sprite_dir}/hoodie/Mon3.png",
                "eyes close neutral": f"{self.sprite_dir}/hoodie/Mon17.png",
                "neutral speaking": f"{self.sprite_dir}/hoodie/Mon4.png",
                "eyes close neutral speaking": f"{self.sprite_dir}/hoodie/Mon18.png",
                "horrified screams": f"{self.sprite_dir}/hoodie/HorrifiedMonika8.png",
                "horrified speaking": f"{self.sprite_dir}/hoodie/HorrifiedMonika5.png",
                "horrified babbling": f"{self.sprite_dir}/hoodie/HorrifiedMonika6.png",
                "horrified surprised": f"{self.sprite_dir}/hoodie/HorrifiedMonika4.png",
                "horrified no words": f"{self.sprite_dir}/hoodie/HorrifiedMonika3.png",
                "horrified really surprised": f"{self.sprite_dir}/hoodie/HorrifiedMonika2.png",
                "horrified": f"{self.sprite_dir}/hoodie/HorrifiedMonika1.png",
                "horrified concerned": f"{self.sprite_dir}/hoodie/HorrifiedMonika7.png",
                "serious": f"{self.sprite_dir}/hoodie/Mon8.png",
                "very serious": f"{self.sprite_dir}/hoodie/Mon21.png",
                "disappointed": f"{self.sprite_dir}/hoodie/Mon21.png",
                "serious pointing speaking": f"{self.sprite_dir}/hoodie/Ika8.png",
                "serious pointing": f"{self.sprite_dir}/hoodie/Ika7.png",
                "serious speaking": f"{self.sprite_dir}/hoodie/Mon9.png",
                "serious pointing eyes close": f"{self.sprite_dir}/hoodie/Ika15.png",
                "serious pointing speaking eyes close": f"{self.sprite_dir}/hoodie/Ika16.png",
                "concerned": f"{self.sprite_dir}/hoodie/Mon6.png",
                "concerned pointing": f"{self.sprite_dir}/hoodie/Ika13.png",
                "concerned pointing speaking": f"{self.sprite_dir}/hoodie/Ika14.png",
                "sad pointing smile looks away": f"{self.sprite_dir}/hoodie/Ika12.png",
                "sad pointing smile": f"{self.sprite_dir}/hoodie/Ika5.png",
                "sad pointing": f"{self.sprite_dir}/hoodie/Ika6.png",
                "sad pointing smile speaking": f"{self.sprite_dir}/hoodie/Ika11.png",
                "smile pointing speaking": f"{self.sprite_dir}/hoodie/Ika10.png",
                "happy pointing speaking": f"{self.sprite_dir}/hoodie/Ika2.png",
                "happy pointing": f"{self.sprite_dir}/hoodie/Ika1.png",
                "neutral pointing speaking": f"{self.sprite_dir}/hoodie/Ika4.png",
                "neutral pointing": f"{self.sprite_dir}/hoodie/Ika3.png",
                "concerned speaking": f"{self.sprite_dir}/hoodie/Mon7.png",
                "embarrass": f"{self.sprite_dir}/hoodie/Mon19.png",
                "blushing with her eyes close": f"{self.sprite_dir}/hoodie/Mon19.png",
                "nervous": f"{self.sprite_dir}/hoodie/Mon13.png",
                "really nervous": f"{self.sprite_dir}/hoodie/Mon15.png",
                "nervous speaking": f"{self.sprite_dir}/hoodie/Mon16.png",
                "nervous laughing": f"{self.sprite_dir}/hoodie/Mon14.png",
                "nervous laughing eyes close": f"{self.sprite_dir}/hoodie/Mon12.png",
            },
            "pajamas": {
                "happy": f"{self.sprite_dir}/pajamas/Mon1.png",
                "smile speaking": f"{self.sprite_dir}/pajamas/Mon2.png",
                "lean smile": f"{self.sprite_dir}/pajamas/3aa.png",
                "lean smile eyes close": f"{self.sprite_dir}/pajamas/3ab.png",
                "lean happy eyes close speaking": f"{self.sprite_dir}/pajamas/3ac.png",
                "lean happy speaking": f"{self.sprite_dir}/pajamas/3ad.png",
                "lean happy wink": f"{self.sprite_dir}/pajamas/3ae.png",
                "eyes close smile": f"{self.sprite_dir}/pajamas/Mon10.png",
                "eyes close smile speaking": f"{self.sprite_dir}/pajamas/Mon11.png",
                "pointing finger smile": f"{self.sprite_dir}/pajamas/Ika9.png",
                "lean wink point smile": f"{self.sprite_dir}/pajamas/3Ika.png",
                "sad": f"{self.sprite_dir}/pajamas/Mon6.png",
                "crying": f"{self.sprite_dir}/pajamas/Mon20.png",
                "sad smile": f"{self.sprite_dir}/pajamas/Mon5.png",
                "neutral": f"{self.sprite_dir}/pajamas/Mon3.png",
                "eyes close neutral": f"{self.sprite_dir}/pajamas/Mon17.png",
                "neutral speaking": f"{self.sprite_dir}/pajamas/Mon4.png",
                "eyes close neutral speaking": f"{self.sprite_dir}/pajamas/Mon18.png",
                "pissed lean": f"{self.sprite_dir}/pajamas/3bd.png",
                "mad speaking lean": f"{self.sprite_dir}/pajamas/3ba.png",
                "mad leaning": f"{self.sprite_dir}/pajamas/3bb.png",
                "mad pitting face lean": f"{self.sprite_dir}/pajamas/3bc.png",
                "horrified screams": f"{self.sprite_dir}/pajamas/HorrifiedMonika8.png",
                "horrified speaking": f"{self.sprite_dir}/pajamas/HorrifiedMonika5.png",
                "horrified babbling": f"{self.sprite_dir}/pajamas/HorrifiedMonika6.png",
                "horrified surprised": f"{self.sprite_dir}/pajamas/HorrifiedMonika4.png",
                "horrified no words": f"{self.sprite_dir}/pajamas/HorrifiedMonika3.png",
                "horrified really surprised": f"{self.sprite_dir}/pajamas/HorrifiedMonika2.png",
                "horrified": f"{self.sprite_dir}/pajamas/HorrifiedMonika1.png",
                "horrified concerned": f"{self.sprite_dir}/pajamas/HorrifiedMonika7.png",
                "serious": f"{self.sprite_dir}/pajamas/Mon8.png",
                "very serious": f"{self.sprite_dir}/pajamas/Mon21.png",
                "disappointed": f"{self.sprite_dir}/pajamas/Mon21.png",
                "serious pointing speaking": f"{self.sprite_dir}/pajamas/Ika8.png",
                "serious pointing": f"{self.sprite_dir}/pajamas/Ika7.png",
                "serious speaking": f"{self.sprite_dir}/pajamas/Mon9.png",
                "serious pointing eyes close": f"{self.sprite_dir}/pajamas/Ika15.png",
                "serious pointing speaking eyes close": f"{self.sprite_dir}/pajamas/Ika16.png",
                "concerned": f"{self.sprite_dir}/pajamas/Mon6.png",
                "concerned pointing": f"{self.sprite_dir}/pajamas/Ika13.png",
                "concerned pointing speaking": f"{self.sprite_dir}/pajamas/Ika14.png",
                "sad pointing smile looks away": f"{self.sprite_dir}/pajamas/Ika12.png",
                "sad pointing smile": f"{self.sprite_dir}/pajamas/Ika5.png",
                "sad pointing": f"{self.sprite_dir}/pajamas/Ika6.png",
                "sad pointing smile speaking": f"{self.sprite_dir}/pajamas/Ika11.png",
                "smile pointing speaking": f"{self.sprite_dir}/pajamas/Ika10.png",
                "happy pointing speaking": f"{self.sprite_dir}/pajamas/Ika2.png",
                "happy pointing": f"{self.sprite_dir}/pajamas/Ika1.png",
                "neutral pointing speaking": f"{self.sprite_dir}/pajamas/Ika4.png",
                "neutral pointing": f"{self.sprite_dir}/pajamas/Ika3.png",
                "concerned speaking": f"{self.sprite_dir}/pajamas/Mon7.png",
                "embarrass": f"{self.sprite_dir}/pajamas/Mon19.png",
                "blushing with her eyes close": f"{self.sprite_dir}/pajamas/Mon19.png",
                "smirk lean": f"{self.sprite_dir}/pajamas/3ca.png",
                "leaning kiss": f"{self.sprite_dir}/pajamas/3cb.png",
                "blushing leaning": f"{self.sprite_dir}/pajamas/3cc.png",
                "surprise speaking lean": f"{self.sprite_dir}/pajamas/3da.png",
                "concerned speaking lean": f"{self.sprite_dir}/pajamas/3ea.png",
                "really...": f"{self.sprite_dir}/pajamas/3fa.png",
                "nervous": f"{self.sprite_dir}/pajamas/Mon13.png",
                "really nervous": f"{self.sprite_dir}/pajamas/Mon15.png",
                "nervous speaking": f"{self.sprite_dir}/pajamas/Mon16.png",
                "nervous laughing": f"{self.sprite_dir}/pajamas/Mon14.png",
                "nervous laughing eyes close": f"{self.sprite_dir}/pajamas/Mon12.png",
            },
            "white summer dress": {
                "happy": f"{self.sprite_dir}/dress/Mon1.png",
                "smile speaking": f"{self.sprite_dir}/dress/Mon2.png",
                "eyes close smile": f"{self.sprite_dir}/dress/Mon10.png",
                "eyes close smile speaking": f"{self.sprite_dir}/dress/Mon11.png",
                "pointing finger smile": f"{self.sprite_dir}/dress/Ika9.png",
                "sad": f"{self.sprite_dir}/dress/Mon6.png",
                "crying": f"{self.sprite_dir}/dress/Mon20.png",
                "sad smile": f"{self.sprite_dir}/dress/Mon5.png",
                "neutral": f"{self.sprite_dir}/dress/Mon3.png",
                "eyes close neutral": f"{self.sprite_dir}/dress/Mon17.png",
                "neutral speaking": f"{self.sprite_dir}/dress/Mon4.png",
                "eyes close neutral speaking": f"{self.sprite_dir}/dress/Mon18.png",
                "horrified screams": f"{self.sprite_dir}/dress/HorrifiedMonika8.png",
                "horrified speaking": f"{self.sprite_dir}/dress/HorrifiedMonika5.png",
                "horrified babbling": f"{self.sprite_dir}/dress/HorrifiedMonika6.png",
                "horrified surprised": f"{self.sprite_dir}/dress/HorrifiedMonika4.png",
                "horrified no words": f"{self.sprite_dir}/dress/HorrifiedMonika3.png",
                "horrified really surprised": f"{self.sprite_dir}/dress/HorrifiedMonika2.png",
                "horrified": f"{self.sprite_dir}/dress/HorrifiedMonika1.png",
                "horrified concerned": f"{self.sprite_dir}/dress/HorrifiedMonika7.png",
                "serious": f"{self.sprite_dir}/dress/Mon8.png",
                "very serious": f"{self.sprite_dir}/dress/Mon21.png",
                "disappointed": f"{self.sprite_dir}/dress/Mon21.png",
                "serious pointing speaking": f"{self.sprite_dir}/dress/Ika8.png",
                "serious pointing": f"{self.sprite_dir}/dress/Ika7.png",
                "serious speaking": f"{self.sprite_dir}/dress/Mon9.png",
                "serious pointing eyes close": f"{self.sprite_dir}/dress/Ika15.png",
                "serious pointing speaking eyes close": f"{self.sprite_dir}/dress/Ika16.png",
                "concerned": f"{self.sprite_dir}/dress/Mon6.png",
                "concerned pointing": f"{self.sprite_dir}/dress/Ika13.png",
                "concerned pointing speaking": f"{self.sprite_dir}/dress/Ika14.png",
                "sad pointing smile looks away": f"{self.sprite_dir}/dress/Ika12.png",
                "sad pointing smile": f"{self.sprite_dir}/dress/Ika5.png",
                "sad pointing": f"{self.sprite_dir}/dress/Ika6.png",
                "sad pointing smile speaking": f"{self.sprite_dir}/dress/Ika11.png",
                "smile pointing speaking": f"{self.sprite_dir}/dress/Ika10.png",
                "happy pointing speaking": f"{self.sprite_dir}/dress/Ika2.png",
                "happy pointing": f"{self.sprite_dir}/dress/Ika1.png",
                "neutral pointing speaking": f"{self.sprite_dir}/dress/Ika4.png",
                "neutral pointing": f"{self.sprite_dir}/dress/Ika3.png",
                "concerned speaking": f"{self.sprite_dir}/dress/Mon7.png",
                "embarrass": f"{self.sprite_dir}/dress/Mon19.png",
                "blushing with her eyes close": f"{self.sprite_dir}/dress/Mon19.png",
                "nervous": f"{self.sprite_dir}/dress/Mon13.png",
                "really nervous": f"{self.sprite_dir}/dress/Mon15.png",
                "nervous speaking": f"{self.sprite_dir}/dress/Mon16.png",
                "nervous laughing": f"{self.sprite_dir}/dress/Mon14.png",
                "nervous laughing eyes close": f"{self.sprite_dir}/dress/Mon12.png",
            },
            "green dress": {
                "happy": f"{self.sprite_dir}/green_dress/Mon1.png",
                "smile speaking": f"{self.sprite_dir}/green_dress/Mon2.png",
                "lean smile": f"{self.sprite_dir}/green_dress/3aa.png",
                "lean smile eyes close": f"{self.sprite_dir}/green_dress/3ab.png",
                "lean happy eyes close speaking": f"{self.sprite_dir}/green_dress/3ac.png",
                "lean happy speaking": f"{self.sprite_dir}/green_dress/3ad.png",
                "lean happy wink": f"{self.sprite_dir}/green_dress/3ae.png",
                "eyes close smile": f"{self.sprite_dir}/green_dress/Mon10.png",
                "eyes close smile speaking": f"{self.sprite_dir}/green_dress/Mon11.png",
                "pointing finger smile": f"{self.sprite_dir}/green_dress/Ika9.png",
                "lean wink point smile": f"{self.sprite_dir}/green_dress/3Ika.png",
                "sad": f"{self.sprite_dir}/green_dress/Mon6.png",
                "crying": f"{self.sprite_dir}/green_dress/Mon20.png",
                "sad smile": f"{self.sprite_dir}/green_dress/Mon5.png",
                "neutral": f"{self.sprite_dir}/green_dress/Mon3.png",
                "eyes close neutral": f"{self.sprite_dir}/green_dress/Mon17.png",
                "neutral speaking": f"{self.sprite_dir}/green_dress/Mon4.png",
                "eyes close neutral speaking": f"{self.sprite_dir}/green_dress/Mon18.png",
                "pissed lean": f"{self.sprite_dir}/green_dress/3bd.png",
                "mad speaking lean": f"{self.sprite_dir}/green_dress/3ba.png",
                "mad leaning": f"{self.sprite_dir}/green_dress/3bb.png",
                "mad pitting face lean": f"{self.sprite_dir}/green_dress/3bc.png",
                "horrified screams": f"{self.sprite_dir}/green_dress/HorrifiedMonika8.png",
                "horrified speaking": f"{self.sprite_dir}/green_dress/HorrifiedMonika5.png",
                "horrified babbling": f"{self.sprite_dir}/green_dress/HorrifiedMonika6.png",
                "horrified surprised": f"{self.sprite_dir}/green_dress/HorrifiedMonika4.png",
                "horrified no words": f"{self.sprite_dir}/green_dress/HorrifiedMonika3.png",
                "horrified really surprised": f"{self.sprite_dir}/green_dress/HorrifiedMonika2.png",
                "horrified": f"{self.sprite_dir}/green_dress/HorrifiedMonika1.png",
                "horrified concerned": f"{self.sprite_dir}/green_dress/HorrifiedMonika7.png",
                "serious": f"{self.sprite_dir}/green_dress/Mon8.png",
                "very serious": f"{self.sprite_dir}/green_dress/Mon21.png",
                "disappointed": f"{self.sprite_dir}/green_dress/Mon21.png",
                "serious pointing speaking": f"{self.sprite_dir}/green_dress/Ika8.png",
                "serious pointing": f"{self.sprite_dir}/green_dress/Ika7.png",
                "serious speaking": f"{self.sprite_dir}/green_dress/Mon9.png",
                "serious pointing eyes close": f"{self.sprite_dir}/green_dress/Ika15.png",
                "serious pointing speaking eyes close": f"{self.sprite_dir}/green_dress/Ika16.png",
                "concerned": f"{self.sprite_dir}/green_dress/Mon6.png",
                "concerned pointing": f"{self.sprite_dir}/green_dress/Ika13.png",
                "concerned pointing speaking": f"{self.sprite_dir}/green_dress/Ika14.png",
                "sad pointing smile looks away": f"{self.sprite_dir}/green_dress/Ika12.png",
                "sad pointing smile": f"{self.sprite_dir}/green_dress/Ika5.png",
                "sad pointing": f"{self.sprite_dir}/green_dress/Ika6.png",
                "sad pointing smile speaking": f"{self.sprite_dir}/green_dress/Ika11.png",
                "smile pointing speaking": f"{self.sprite_dir}/green_dress/Ika10.png",
                "happy pointing speaking": f"{self.sprite_dir}/green_dress/Ika2.png",
                "happy pointing": f"{self.sprite_dir}/green_dress/Ika1.png",
                "neutral pointing speaking": f"{self.sprite_dir}/green_dress/Ika4.png",
                "neutral pointing": f"{self.sprite_dir}/green_dress/Ika3.png",
                "concerned speaking": f"{self.sprite_dir}/green_dress/Mon7.png",
                "embarrass": f"{self.sprite_dir}/green_dress/Mon19.png",
                "blushing with her eyes close": f"{self.sprite_dir}/green_dress/Mon19.png",
                "smirk lean": f"{self.sprite_dir}/green_dress/3ca.png",
                "leaning kiss": f"{self.sprite_dir}/green_dress/3cb.png",
                "blushing leaning": f"{self.sprite_dir}/green_dress/3cc.png",
                "surprise speaking lean": f"{self.sprite_dir}/green_dress/3da.png",
                "concerned speaking lean": f"{self.sprite_dir}/green_dress/3ea.png",
                "really...": f"{self.sprite_dir}/green_dress/3fa.png",
                "nervous": f"{self.sprite_dir}/green_dress/Mon13.png",
                "really nervous": f"{self.sprite_dir}/green_dress/Mon15.png",
                "nervous speaking": f"{self.sprite_dir}/green_dress/Mon16.png",
                "nervous laughing": f"{self.sprite_dir}/green_dress/Mon14.png",
                "nervous laughing eyes close": f"{self.sprite_dir}/green_dress/Mon12.png",
            }
        }

        self.error_sprite = {
            "error": f"{self.sprite_dir}/bug/G1.png",
            "glitching": f"{self.sprite_dir}/bug/G5.gif"
        }

        self.sprites_by_outfit = {}
        self._load_sprites()

        # valid emotions (computed from loaded sprites)
        self.valid = self._extract_all_emotions()

        print("[DEBUG] Loaded sprites:", self.sprites_by_outfit)

    # ---------------- Classify ----------------
    async def classify(self, text: str) -> str:
        """Classify text into one of the valid emotion labels using OpenAI."""
        from OpenAIKeys import safe_call, key_manager  # already in your project
        model_priority = ["gpt-5-mini", "gpt-5", "gpt-3.5-turbo"]

        prompt = (
            "Return ONLY one label from this list:\n"
            + ", ".join(self.valid) +
            "\n\nClassify the emotion of the following message using exactly one of the labels above."
        )

        for model in model_priority:
            async def call_fn(client):
                return await client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": text}
                    ]
                )

            try:
                response = await safe_call(key_manager, call_fn)
                if not response or not response.choices:
                    continue

                raw = response.choices[0].message.content.strip().lower()

                for label in self.valid:
                    if label.lower() in raw:
                        print(f"[Emotion Classifier] {model} → {label}")
                        return label

                print(f"[Emotion Classifier WARN] Unexpected response: {raw}")

            except Exception as e:
                print(f"[Emotion Classifier Error] {model} → {e}")
                continue

        return "neutral"

    # ---------------- Validation ----------------
    def valid_for_outfit(self, emotion: str, outfit: str = None):
        """
        If outfit is given, check only that outfit.
        If not, search all outfits for the emotion.
        """
        if outfit:
            outfit = outfit.lower()
            return emotion in self.sprites_by_outfit.get(outfit, {})

        # If no outfit, try to find emotion in any outfit
        for emo_dict in self.sprites_by_outfit.values():
            if emotion in emo_dict:
                return True
        return False

    # ---------------- Commands ----------------
    def get_emotions_for_outfit(self, outfit: str):
        return list(self.sprites_by_outfit.get(outfit.lower(), {}).keys())

    def command_outfit(self, outfit: str) -> str:
        outfit = outfit.lower()
        return list(self.sprites_by_outfit.get(outfit, {}).keys())

    def command_sprite(self, emotion: str, outfit: str) -> str:
        return self.get_sprite(emotion, outfit)

    # ---------------- Sprite Handling ----------------
    def get_sprite(self, emotion: str, outfit: str) -> str:
        today = datetime.date.today()
        
        outfit = outfit.lower()
        emotion = emotion.lower()

        if outfit not in self.EXPRESSION_SPRITES:
            print(f"[WARN] Outfit '{outfit}' not found. Using school uniform.")
            outfit = "school uniform"

        sprites = self.EXPRESSION_SPRITES[outfit]

        # 🎂 Override Sep 21: Only one special expression allowed
        if today.month == 9 and today.day == 21:
            allowed_expressions = "green dress"   # change to the outfit you want
            if emotion not in allowed_expressions:
                # fallback: pick the first allowed one
                emotion = allowed_expressions[0]

        if emotion in sprites:
            return sprites[emotion]

        if "neutral" in sprites:
            return sprites["neutral"]

        print(f"[ERROR] No valid sprite found for {emotion}/{outfit}.")
        return self.error_sprite

    # ---------------- Sprite Loading ----------------
    def _load_sprites(self):
        # Just copy the dictionary of emotions → paths
        self.sprites_by_outfit = {
            outfit.lower(): emotions
            for outfit, emotions in self.EXPRESSION_SPRITES.items()
        }

    def _extract_all_emotions(self):
        emotions = set()
        for mapping in self.EXPRESSION_SPRITES.values():
            for emotion in mapping:
                emotions.add(emotion.lower())
        return sorted(emotions)

    # ---------------- Outfit Variants ----------------
    def _pick_casual_variant(self, outfit: str) -> str:
        variants = self.CASUAL_VARIANTS.get(outfit.lower(), [])
        return random.choice(variants) if variants else outfit
