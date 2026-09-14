"""Heuristic semantic analysis of transcript segments — no LLM required.

Expanded v2: ~3x larger word banks, internet-speak patterns, narrative arc detection,
question-type detection, cliffhanger signals, relatability markers, educational hooks,
and a more nuanced multi-signal scoring formula.
"""
import re
import math
from typing import Optional


# ── Hook phrases ───────────────────────────────────────────────────────────────
# Expanded from 38 → 90+ patterns covering classic, podcast, TikTok/YouTube styles

HOOK_PHRASES = [
    # Classic attention-grabbers
    "you won't believe", "i can't believe", "nobody knows", "nobody talks about",
    "the secret", "here's the thing", "here's what", "here's how", "here's why",
    "most people don't", "most people think", "most people never",
    "stop doing", "stop saying", "stop telling",
    "the reason why", "the real reason", "the truth about", "the truth is",
    "what if i told you", "what nobody tells you",
    "i never told anyone", "i've never told anyone", "i've never said this",
    "wait", "wait wait wait", "hold on", "hold on hold on",
    "turns out", "it turns out",
    "you need to know", "you need to hear",
    "this is why", "that's why", "and that's when",
    "did you know", "did you hear",
    "the problem is", "the biggest problem",
    "the biggest mistake", "my biggest mistake",
    "i learned", "i realized", "i discovered", "i found out",
    "actually works", "it actually", "this actually",
    "no way", "there's no way", "i had no idea",
    "i was wrong", "i was completely wrong",
    "everything changed", "changed everything",
    "the moment i", "that's the moment",
    "listen to this", "listen",
    "imagine", "imagine if",
    "what happened was", "here's what happened",
    "and then", "but then", "so then",
    "plot twist", "spoiler",
    "confession", "i have to confess",
    "honest", "honestly", "to be honest", "to be completely honest",
    "unpopular opinion", "controversial",
    "life changing", "game changer", "game changing",
    # Educational / informational hooks
    "what most people get wrong", "the one thing", "one simple",
    "i'm going to show you", "let me show you", "let me explain",
    "here's the catch", "here's the problem", "here's the secret",
    "the key is", "the answer is", "the solution is",
    "step by step", "the formula", "the method",
    "this changed my life", "changed my mind", "changed how i",
    "research shows", "studies show", "science says", "experts say",
    "the data shows", "the statistics", "the numbers",
    # Personal story hooks
    "true story", "real story", "this actually happened",
    "so i was", "so i did", "so i tried", "so i went",
    "last year i", "last month i", "last week i",
    "when i was", "back when i", "back in",
    "at one point", "at that point", "that was the moment",
    "everything i knew", "nothing was the same",
    # Question-based hooks
    "have you ever", "have you noticed", "have you seen",
    "why does", "why do we", "why is it that",
    "what would you do", "what if you", "what happens when",
    "how many of you", "how often do you",
    # Engagement / curiosity gap hooks
    "keep watching", "stay with me", "don't go anywhere",
    "i'll get to that", "by the end of this",
    "the reason will shock you", "and the reason why is",
    "i'll explain", "let me tell you", "you're going to want to hear this",
    # Controversy / opinion hooks
    "hot take", "controversial opinion", "people hate me for saying this",
    "i got cancelled", "i got called out", "i was exposed",
    "i'm not sorry", "i said what i said", "fight me on this",
    "nobody wants to talk about", "we need to talk about",
    "can we talk about", "can we please talk about",
]

# ── Emotion word banks — expanded ─────────────────────────────────────────────

EMOTION_WORDS = {
    "excitement": [
        "amazing", "incredible", "insane", "unbelievable", "mind-blowing",
        "awesome", "fantastic", "epic", "legendary", "wild", "crazy",
        "holy", "oh my", "oh my god", "omg", "wow", "woah", "whoa",
        "obsessed", "addicted", "cant stop", "can't stop", "hooked",
        "fire", "lit", "bussin", "banger", "slaps", "it slaps",
        "goes hard", "absolute", "insanely", "ridiculously good",
        "best thing", "best ever", "greatest", "goat",
    ],
    "surprise": [
        "shocked", "shocked me", "surprised", "surprising", "unexpected",
        "never expected", "didn't expect", "out of nowhere", "suddenly",
        "all of a sudden", "completely caught", "caught me off guard",
        "blew my mind", "mind blown", "couldn't believe", "wait what",
        "no way", "absolutely not", "what just happened", "plot twist",
        "out of left field", "blindsided", "caught off guard",
        "out of the blue", "randomly", "completely random",
    ],
    "tension": [
        "terrifying", "terrified", "scared", "frightened", "nervous",
        "anxious", "stressed", "panic", "panicking", "danger", "dangerous",
        "risky", "risk", "threatened", "threatening", "worried", "worry",
        "dread", "dreaded", "dreading", "nightmare", "worst case",
        "ticking clock", "running out of time", "last chance",
        "heart racing", "hands shaking", "stomach dropped",
        "couldn't breathe", "throat tight", "adrenaline",
    ],
    "humor": [
        "hilarious", "funny", "laughing", "lol", "lmao", "haha", "hahaha",
        "joke", "joking", "kidding", "just kidding", "absurd", "ridiculous",
        "clown", "cringe", "this is so dumb", "i'm crying", "dead",
        "i'm dead", "i'm deceased", "no literally", "i cannot",
        "the audacity", "the nerve", "unhinged", "chaotic", "feral",
        "not me", "it's giving", "the way i", "living for this",
        "rent free", "in my head rent free", "lowkey",
    ],
    "anger": [
        "angry", "furious", "outraged", "disgusted", "disrespected",
        "disrespect", "unacceptable", "fed up", "had enough", "enough is enough",
        "not okay", "absolutely not", "no way", "appalling", "infuriating",
        "makes me sick", "makes me mad", "drives me crazy", "drives me insane",
        "can't stand", "can't deal", "done with", "over it",
        "calling this out", "holding them accountable", "not letting this slide",
        "this needs to stop", "enough", "enough already",
    ],
    "sadness": [
        "sad", "crying", "cried", "tears", "heartbroken", "devastated",
        "disappointed", "terrible", "awful", "horrible", "gutted",
        "crushed", "destroyed", "lost everything", "fell apart",
        "broke down", "couldn't handle", "the hardest", "darkest",
        "rock bottom", "lowest point", "hit rock bottom",
        "couldn't get out of bed", "stopped caring", "gave up",
    ],
    "revelation": [
        "realized", "figured out", "found out", "discovered", "learned",
        "now i know", "turns out", "it turns out", "truth", "true story",
        "real story", "what really", "the real", "the truth",
        "the answer", "the reason", "the secret", "finally understood",
        "connecting the dots", "it all makes sense", "suddenly clear",
        "clicked", "it clicked", "everything clicked", "now i get it",
        "i finally get it", "the missing piece", "all along",
    ],
    "inspiration": [
        "inspiring", "motivated", "motivated me", "push through",
        "never give up", "keep going", "worth it", "so worth it",
        "changed everything", "turned my life around", "best decision",
        "grateful", "thankful", "blessed", "overcome", "overcame",
        "didn't stop", "pushed through", "made it", "we made it",
        "finally", "finally did it", "proof that", "possible",
        "you can do this", "you can do it", "believe me",
    ],
    "relatability": [
        "we've all been there", "you know the feeling", "you know what i mean",
        "happens to everyone", "guilty", "guilty of this", "same",
        "literally me", "this is me", "oh god that's me",
        "i do this too", "anyone else", "am i the only one",
        "tell me i'm not the only one", "normalize this",
        "real talk", "no cap", "i'm not even lying", "deadass",
        "facts", "big facts", "on god", "for real",
    ],
}

# ── Conflict / drama words ─────────────────────────────────────────────────────

CONFLICT_WORDS = [
    "fight", "fighting", "argument", "arguing", "argued", "disagree", "disagreed",
    "disagreement", "confronted", "confrontation", "called out", "called me out",
    "accused", "accuse", "lied", "lying", "cheat", "cheated", "cheating",
    "betrayed", "betrayal", "backstab", "two-faced", "fake", "fraud",
    "against", "versus", "debate", "controversy", "controversial", "drama",
    "cancel", "cancelled", "exposed", "expose",
    "toxic", "abuse", "abusive", "manipulative", "gaslit", "gaslighting",
    "red flag", "red flags", "walking on eggshells", "nothing i did",
    "cut them off", "blocked them", "left", "walked out", "walked away",
    "stood up for myself", "finally said", "confronted them",
    "went off", "snapped", "lost it", "couldn't take it anymore",
]

# ── Story structure signals ────────────────────────────────────────────────────

STORY_SETUP_WORDS = [
    "so", "so basically", "ok so", "okay so", "alright so",
    "yesterday", "last week", "last month", "last year", "the other day",
    "a while ago", "back in", "back when", "when i was",
    "i was", "i went", "i got", "i had",
    "here's what happened", "so what happened",
    "let me tell you", "let me explain",
    "for context", "for those who don't know",
    "basically", "essentially", "long story short",
    "it started when", "it all started", "this all started",
    "there was this", "there was a",
    "so i met", "so i found", "so i saw", "so i heard",
]

ESCALATION_WORDS = [
    "then", "and then", "but then", "so then", "after that",
    "suddenly", "out of nowhere", "all of a sudden",
    "things got", "it got", "it got worse", "it escalated",
    "next thing", "the next thing i know",
    "that's when", "that's when things",
    "started to", "began to",
    "more and more", "worse and worse",
    "kept", "kept getting", "kept happening",
    "couldn't stop", "wouldn't stop",
    "things got serious", "things got real",
    "hours later", "days later", "minutes later",
]

PAYOFF_WORDS = [
    "and that's", "so that's", "turns out", "ended up",
    "final", "finally", "in the end", "at the end",
    "the result", "the outcome",
    "i survived", "we made it", "we did it",
    "it worked", "it didn't work",
    "punchline", "the punchline is",
    "moral", "moral of the story", "lesson learned",
    "never again", "first and last time",
    "worth it", "not worth it",
    "full circle", "came full circle",
    "now i know", "now i understand", "looking back",
    "i'll never forget", "changed everything",
    "that was it", "that was the moment", "that's what did it",
]

# ── Cliffhanger / anticipation signals ────────────────────────────────────────

CLIFFHANGER_WORDS = [
    "you'll never guess", "guess what happened", "guess what they said",
    "and you won't believe what", "here's where it gets crazy",
    "here's where it gets good", "it gets worse", "it gets better",
    "wait for it", "but wait", "but here's the thing",
    "and that's not even", "that's not the worst part", "that's not the best part",
    "i'm not done", "there's more", "but there's a catch",
    "oh but it gets better", "oh but it gets worse",
    "brace yourself", "you're not ready for this",
]

# ── Question patterns ──────────────────────────────────────────────────────────

RHETORICAL_QUESTIONS = [
    "why would anyone", "why do people", "how is that possible",
    "what kind of person", "how could someone",
    "is it just me", "am i crazy", "am i wrong",
    "does anyone else", "can anyone explain",
    "why aren't we talking about", "why is nobody talking about",
]

# ── Personal narrative markers ─────────────────────────────────────────────────

PERSONAL_STORY_MARKERS = [
    "i grew up", "growing up i", "as a kid", "when i was a kid",
    "my parents", "my mom", "my dad", "my family",
    "at my job", "at work", "my boss", "my coworker", "my colleague",
    "my friend", "my best friend", "my ex", "my partner", "my girlfriend", "my boyfriend",
    "my husband", "my wife", "my relationship",
    "in school", "in college", "in high school", "my teacher",
    "first time i", "the day i", "the night i", "the moment i",
    "i'll never forget", "i still remember", "to this day",
]

# ── Educational / value-add markers ───────────────────────────────────────────

EDUCATIONAL_MARKERS = [
    "here's what you need to know", "here's how it works",
    "the way it works is", "the reason this happens",
    "most people don't realize", "most people don't know",
    "what they don't tell you", "what nobody tells you",
    "the correct way", "the right way", "the wrong way",
    "common misconception", "myth", "debunking", "actually false",
    "technically", "technically speaking", "here's the science",
    "the research", "according to", "studies found",
    "tip", "pro tip", "life hack", "hack", "trick",
    "this works because", "here's why this works",
]

# ── Standalone detection ───────────────────────────────────────────────────────

STANDALONE_PENALTY_STARTERS = [
    "he", "she", "it", "they", "we", "that", "this", "those", "these",
    "him", "her", "them", "his", "hers", "their",
    "which", "who", "what", "where", "when", "how",
    "but", "and", "or", "so", "then", "because", "since", "although",
]

STANDALONE_INTRO_PHRASES = [
    "my name", "i'm", "we're", "this is", "today we", "today i",
    "welcome to", "in this video", "in today's video",
    "so today", "so basically", "ok so", "okay so",
    "long story short", "let me explain", "let me tell you",
    "real quick", "quick story", "storytime",
    "true story", "this really happened",
]


# ── Spanish language support ──────────────────────────────────────────────────

_SPANISH_MARKERS = frozenset({
    "que", "de", "en", "el", "la", "los", "las", "es", "se", "un", "una",
    "y", "del", "lo", "su", "por", "con", "para", "al", "como", "me",
    "le", "también", "pero", "más", "ya", "yo", "si", "muy",
    "todo", "fue", "era", "cuando", "te", "esto", "sí",
    "porque", "hay", "este", "esta", "ese", "esa",
    "tienen", "tiene", "pueden", "puede", "están", "está",
    "nos", "les", "ellos", "ellas", "nosotros",
    "qué", "cómo", "dónde", "cuándo", "quién", "cuál",
})

HOOK_PHRASES_ES = [
    "no vas a creer", "no puedo creer", "nadie sabe", "nadie habla de",
    "el secreto", "aquí está la cosa", "aquí está cómo", "aquí está por qué",
    "la mayoría no", "la mayoría cree", "la mayoría nunca",
    "deja de hacer", "deja de decir",
    "la razón", "la verdad sobre", "la verdad es",
    "y si te dijera", "lo que nadie te dice",
    "nunca se lo dije a nadie", "nunca lo había dicho",
    "espera", "espera espera", "un momento",
    "resulta que",
    "necesitas saber", "necesitas escuchar",
    "por eso", "eso es por qué", "y entonces",
    "¿sabías que", "¿te enteraste",
    "el problema es", "el mayor problema",
    "el mayor error", "mi mayor error",
    "aprendí", "me di cuenta", "descubrí", "me enteré",
    "en serio funciona", "de verdad funciona",
    "imposible", "no hay manera", "no lo sabía",
    "estaba equivocado", "me equivoqué totalmente",
    "todo cambió", "cambió todo",
    "el momento en que", "ese fue el momento",
    "escucha esto", "escucha",
    "imagina", "imagínate",
    "lo que pasó fue", "esto es lo que pasó",
    "y luego", "pero luego",
    "giro de guion", "spoiler",
    "confesión", "tengo que confesar",
    "honesto", "honestamente", "siendo honesto",
    "opinión impopular", "polémico",
    "cambió mi vida", "me cambió la vida",
    "lo que mucha gente hace mal", "una sola cosa",
    "te voy a mostrar", "déjame mostrarte", "déjame explicar",
    "el truco es", "la respuesta es", "la solución es",
    "paso a paso", "la fórmula", "el método",
    "los estudios muestran", "la ciencia dice", "los expertos dicen",
    "historia real", "esto realmente pasó",
    "cuando era", "hace tiempo", "antes de esto",
    "en algún punto", "en ese momento",
    "¿alguna vez", "¿lo has notado", "¿lo has visto",
    "¿por qué", "¿cómo es que",
    "sigue viendo", "quédate conmigo",
    "ya llego a eso", "al final de esto",
    "te explico", "te cuento", "vas a querer escuchar esto",
    "opinión caliente", "opinión polémica",
    "nadie quiere hablar de", "tenemos que hablar de",
    "¿podemos hablar de",
]

EMOTION_WORDS_ES = {
    "excitement": [
        "increíble", "insano", "impresionante", "alucinante",
        "genial", "fantástico", "épico", "legendario", "salvaje", "loco",
        "dios mío", "ay dios", "guau", "wow",
        "obsesionado", "enganchado", "adicto",
        "lo máximo", "brutal",
        "lo mejor", "lo mejor de todo", "el mejor",
    ],
    "surprise": [
        "sorprendido", "me sorprendió", "sorpresa", "inesperado",
        "nunca esperé", "no esperaba", "de la nada", "de repente",
        "de golpe", "me pilló por sorpresa",
        "me voló la mente", "no podía creerlo", "espera qué",
        "imposible", "qué fue eso", "giro inesperado",
        "de pronto", "completamente aleatorio",
    ],
    "tension": [
        "aterrador", "aterrado", "asustado", "nervioso",
        "ansioso", "estresado", "pánico", "peligro", "peligroso",
        "arriesgado", "riesgo", "amenazado", "preocupado",
        "terror", "pesadilla",
        "contra el tiempo", "última oportunidad",
        "corazón acelerado", "adrenalina",
    ],
    "humor": [
        "hilarante", "gracioso", "riéndome", "jajaja", "jaja",
        "chiste", "broma", "en broma", "absurdo", "ridículo",
        "me muero de risa", "no puede ser", "no lo aguanto",
        "qué caradurez", "desquiciado", "caótico",
    ],
    "anger": [
        "enojado", "furioso", "indignado", "asqueado",
        "inaceptable", "harto", "ya no aguanto", "ya basta",
        "no está bien", "indignante",
        "me enfurece", "me saca de quicio", "no lo tolero",
        "ya me tiene harto",
    ],
    "sadness": [
        "triste", "llorando", "lloré", "lágrimas", "desconsolado",
        "devastado", "decepcionado", "terrible", "horrible",
        "destrozado", "destruido",
        "me rompí", "no pude",
        "fondo del pozo", "punto más bajo",
    ],
    "revelation": [
        "me di cuenta", "descubrí", "me enteré", "aprendí",
        "ahora sé", "resulta que", "la verdad", "historia real",
        "lo que realmente", "la verdad es",
        "la respuesta", "la razón", "el secreto", "finalmente entendí",
        "todo tiene sentido", "de repente claro",
        "todo encajó", "la pieza faltante",
    ],
    "inspiration": [
        "inspirador", "motivado", "me motivó", "seguir adelante",
        "nunca rendirse", "seguir", "valió la pena",
        "cambió todo", "cambió mi vida", "la mejor decisión",
        "agradecido", "bendecido", "superar", "superé",
        "no paré", "lo logré", "lo logramos",
        "prueba de que", "posible",
    ],
    "relatability": [
        "todos hemos estado ahí", "sabes la sensación",
        "le pasa a todos", "culpable",
        "igualito", "literalmente yo", "ese soy yo",
        "yo también lo hago", "¿alguien más",
        "no soy el único", "normalizar esto",
        "en serio", "sin filtro",
    ],
}

CONFLICT_WORDS_ES = [
    "pelea", "peleando", "discusión", "discutiendo", "discutí", "en desacuerdo",
    "enfrenté", "confrontación", "lo confronté", "señalé",
    "acusado", "acusar", "mentí", "mintiendo", "trampa", "traicionó", "traición",
    "hipócrita", "dos caras", "falso", "fraude",
    "contra", "versus", "debate", "polémica", "polémico", "drama",
    "cancelar", "cancelado", "expuesto", "exponer",
    "tóxico", "abuso", "abusivo", "manipulador", "manipuladora",
    "señal de alerta", "señales de alerta",
    "lo corté", "lo bloqueé", "me fui", "me salí",
    "me defendí", "finalmente dije",
    "explotó", "no lo aguanté más",
]

STORY_SETUP_WORDS_ES = [
    "bueno", "básicamente", "a ver",
    "ayer", "la semana pasada", "el mes pasado", "el año pasado", "el otro día",
    "hace un tiempo", "cuando era", "cuando yo",
    "yo estaba", "fui", "tenía",
    "esto es lo que pasó", "lo que pasó fue",
    "déjame contarte", "déjame explicar",
    "para poner en contexto", "para los que no saben",
    "larga historia corta",
    "todo empezó cuando", "así empezó todo",
    "entonces conocí", "entonces encontré", "entonces vi",
]

ESCALATION_WORDS_ES = [
    "entonces", "y entonces", "pero entonces", "después de eso",
    "de repente", "de la nada", "de golpe",
    "las cosas se pusieron", "se puso peor", "escaló",
    "lo siguiente que sé",
    "empezó a", "comenzó a",
    "cada vez más", "peor y peor",
    "no paraba", "no se detenía",
    "horas después", "días después", "minutos después",
]

PAYOFF_WORDS_ES = [
    "y así", "resulta que", "terminó siendo",
    "finalmente", "al final", "al final de cuentas",
    "el resultado", "el desenlace",
    "sobreviví", "lo logramos", "lo hicimos",
    "funcionó", "no funcionó",
    "la moraleja", "la lección",
    "nunca más", "primera y última vez",
    "valió la pena", "no valió la pena",
    "ahora entiendo", "mirando atrás",
    "nunca lo olvidaré", "cambió todo",
    "eso fue", "ese fue el momento",
]

CLIFFHANGER_WORDS_ES = [
    "nunca adivinarás", "adivina qué pasó", "adivina qué dijeron",
    "y no vas a creer lo que", "aquí es donde se pone loco",
    "aquí es donde se pone bueno", "se pone peor", "se pone mejor",
    "espéralo", "pero espera", "pero aquí está la cosa",
    "y eso no es todo", "eso no es lo peor", "eso no es lo mejor",
    "no he terminado", "hay más", "pero hay un giro",
    "prepárate", "no estás listo para esto",
]

RHETORICAL_QUESTIONS_ES = [
    "por qué alguien", "por qué la gente", "cómo es posible",
    "qué clase de persona", "cómo puede alguien",
    "¿estoy loco", "¿estoy equivocado",
    "¿alguien más", "¿puede alguien explicar",
    "por qué no estamos hablando de", "por qué nadie habla de",
]

PERSONAL_STORY_MARKERS_ES = [
    "crecí", "de niño", "cuando era niño", "cuando era chico",
    "mis padres", "mi mamá", "mi papá", "mi familia",
    "en mi trabajo", "en el trabajo", "mi jefe", "mi compañero",
    "mi amigo", "mi mejor amigo", "mi ex", "mi pareja", "mi novia", "mi novio",
    "mi esposo", "mi esposa", "mi relación",
    "en la escuela", "en la universidad", "en el colegio", "mi maestro", "mi profesor",
    "la primera vez que", "el día que", "la noche que", "el momento en que",
    "nunca lo olvidaré", "todavía lo recuerdo", "hasta el día de hoy",
]

EDUCATIONAL_MARKERS_ES = [
    "esto es lo que necesitas saber", "así es como funciona",
    "la forma en que funciona", "la razón por la que pasa",
    "la mayoría no se da cuenta", "la mayoría no sabe",
    "lo que no te dicen", "lo que nadie te dice",
    "la forma correcta", "la manera correcta", "la manera incorrecta",
    "error común", "mito", "en realidad falso",
    "técnicamente", "la ciencia dice",
    "la investigación", "según", "los estudios encontraron",
    "consejo", "truco de vida", "truco",
    "funciona porque", "por eso funciona",
]

STANDALONE_PENALTY_STARTERS_ES = [
    "él", "ella", "eso", "ellos", "ellas", "nosotros",
    "ese", "esta", "estos", "estas",
    "le", "les", "su", "sus",
    "cual", "quien",
    "pero", "porque", "aunque", "mientras",
    "y", "o",
]

STANDALONE_INTRO_PHRASES_ES = [
    "me llamo", "soy", "somos", "esto es", "hoy",
    "bienvenidos", "en este video", "en el video de hoy",
    "así que hoy", "básicamente", "a ver",
    "larga historia corta", "déjame explicar", "les voy a contar",
    "historia rápida", "historia",
    "historia real", "esto realmente pasó",
]

_REASON_TRANSLATIONS_ES = {
    "Strong opening hook":       "Hook de apertura potente",
    "Multiple hook phrases":     "Múltiples frases gancho",
    "Hook phrase detected":      "Frase gancho detectada",
    "High excitement energy":    "Alta energía de emoción",
    "Surprise/shock moment":     "Momento de sorpresa",
    "Tension and stakes":        "Tensión y consecuencias",
    "Humor detected":            "Humor detectado",
    "Emotional confrontation":   "Confrontación emocional",
    "Revelation or discovery":   "Revelación o descubrimiento",
    "Inspirational content":     "Contenido inspiracional",
    "Highly relatable":          "Muy identificable",
    "High conflict engagement":  "Alta carga de conflicto",
    "Conflict present":          "Conflicto presente",
    "Strong educational value":  "Alto valor educativo",
    "Educational content":       "Contenido educativo",
    "Personal narrative":        "Narrativa personal",
    "Cliffhanger moment":        "Momento de suspenso",
    "Complete story arc":        "Arco narrativo completo",
    "Setup + escalation":        "Planteamiento + escalada",
    "Strong payoff":             "Desenlace potente",
    "Exceptional hook strength": "Fuerza de hook excepcional",
    "High emotional intensity":  "Alta intensidad emocional",
}


def _detect_language(words: list[dict]) -> str:
    """Return 'es' if Spanish content is detected, 'en' otherwise."""
    if not words:
        return "en"
    tokens = [w["word"].lower().strip(".,!?\"'¡¿;:") for w in words]
    hits = sum(1 for t in tokens if t in _SPANISH_MARKERS)
    return "es" if hits / max(len(tokens), 1) >= 0.12 else "en"


# ── Core analysis function ─────────────────────────────────────────────────────

def analyze_segment(words: list[dict], start_s: float, end_s: float) -> dict:
    """Return full semantic analysis for a word-level transcript segment."""
    if not words:
        return _empty_result(start_s)

    w_in = [w for w in words if w["start"] >= start_s - 0.1 and w["end"] <= end_s + 0.1]
    if not w_in:
        return _empty_result(start_s)

    text = " ".join(w["word"] for w in w_in).lower()
    text_raw = " ".join(w["word"] for w in w_in)
    duration = max(end_s - start_s, 1.0)

    # Language detection — select word banks accordingly
    lang = _detect_language(w_in)
    if lang == "es":
        _hooks        = HOOK_PHRASES_ES
        _emotions     = EMOTION_WORDS_ES
        _conflicts    = CONFLICT_WORDS_ES
        _setup_w      = STORY_SETUP_WORDS_ES
        _escalation_w = ESCALATION_WORDS_ES
        _payoff_w     = PAYOFF_WORDS_ES
        _cliffh_w     = CLIFFHANGER_WORDS_ES
        _rhetorical_w = RHETORICAL_QUESTIONS_ES
        _educational_w = EDUCATIONAL_MARKERS_ES
        _personal_w   = PERSONAL_STORY_MARKERS_ES
        _penalty_w    = STANDALONE_PENALTY_STARTERS_ES
        _intro_w      = STANDALONE_INTRO_PHRASES_ES
    else:
        _hooks        = HOOK_PHRASES
        _emotions     = EMOTION_WORDS
        _conflicts    = CONFLICT_WORDS
        _setup_w      = STORY_SETUP_WORDS
        _escalation_w = ESCALATION_WORDS
        _payoff_w     = PAYOFF_WORDS
        _cliffh_w     = CLIFFHANGER_WORDS
        _rhetorical_w = RHETORICAL_QUESTIONS
        _educational_w = EDUCATIONAL_MARKERS
        _personal_w   = PERSONAL_STORY_MARKERS
        _penalty_w    = STANDALONE_PENALTY_STARTERS
        _intro_w      = STANDALONE_INTRO_PHRASES

    # ── Emotion scoring — 8 categories, weighted by impact ────────────────────
    emotion_hits = {}
    for emo, elist in _emotions.items():
        hits = sum(1 for e in elist if e in text)
        if hits:
            emotion_hits[emo] = hits
    high_impact_emotions = {"excitement", "tension", "anger", "sadness", "surprise"}
    raw_emotion = sum(v for emo, v in emotion_hits.items() if emo in high_impact_emotions)
    support_emotion = sum(v for emo, v in emotion_hits.items() if emo not in high_impact_emotions)
    emotion_score = min(1.0, raw_emotion * 0.13 + support_emotion * 0.07)

    # ── Hook strength ──────────────────────────────────────────────────────────
    first_words = " ".join(w["word"] for w in w_in[:15]).lower()
    hook_hits = sum(1 for p in _hooks if p in text)
    hook_in_opening = sum(1 for p in _hooks if p in first_words)
    cliffhanger_hits = sum(1 for p in _cliffh_w if p in text)
    rhetorical_hits = sum(1 for p in _rhetorical_w if p in text)
    hook_strength = min(1.0,
        hook_hits * 0.14 +
        hook_in_opening * 0.22 +
        cliffhanger_hits * 0.10 +
        rhetorical_hits * 0.08
    )
    opening_text = text[:120]
    if "?" in opening_text or "¿" in opening_text:
        hook_strength = min(1.0, hook_strength + 0.12)
    if "!" in opening_text or "¡" in opening_text:
        hook_strength = min(1.0, hook_strength + 0.08)

    # ── Semantic interest — extended signal mix ────────────────────────────────
    conflict_hits = sum(1 for c in _conflicts if c in text)
    educational_hits = sum(1 for e in _educational_w if e in text)
    personal_hits = sum(1 for p in _personal_w if p in text)
    semantic_interest = min(1.0,
        hook_strength * 0.35 +
        emotion_score * 0.30 +
        min(1.0, conflict_hits * 0.18) * 0.20 +
        min(1.0, educational_hits * 0.25) * 0.10 +
        min(1.0, personal_hits * 0.20) * 0.05
    )

    # Story structure bonus
    has_setup = any(p in text for p in _setup_w)
    has_escalation = any(p in text for p in _escalation_w)
    has_payoff = any(p in text for p in _payoff_w)
    has_cliffhanger = any(p in text for p in _cliffh_w)
    story_bonus = (
        has_setup * 0.10 +
        has_escalation * 0.07 +
        has_payoff * 0.13 +
        has_cliffhanger * 0.08
    )
    semantic_interest = min(1.0, semantic_interest + story_bonus)

    # ── Sub-scores ─────────────────────────────────────────────────────────────
    revelation_words_found = sum(1 for r in _emotions["revelation"] if r in text)
    revelation_score = min(1.0, revelation_words_found * 0.20)

    humor_words_found = sum(1 for h in _emotions["humor"] if h in text)
    humor_score = min(1.0, humor_words_found * 0.18)

    relatability_hits = sum(1 for r in _emotions["relatability"] if r in text)
    relatability_score = min(1.0, relatability_hits * 0.25)

    conflict_score = min(1.0, conflict_hits * 0.18)

    # ── Standalone value ───────────────────────────────────────────────────────
    first_word = w_in[0]["word"].lower().strip(".,!?¡¿")
    standalone_penalty = 0.30 if first_word in _penalty_w else 0.0
    standalone_bonus = 0.0
    if any(p in text for p in _intro_w):
        standalone_bonus += 0.20
    if personal_hits >= 2:
        standalone_bonus += 0.10
    if has_setup and has_payoff:
        standalone_bonus += 0.15
    standalone_value = max(0.1, min(1.0, 0.5 + standalone_bonus - standalone_penalty))

    # ── Shareability ───────────────────────────────────────────────────────────
    shareability = min(1.0,
        hook_strength      * 0.28 +
        emotion_score      * 0.22 +
        revelation_score   * 0.18 +
        humor_score        * 0.14 +
        conflict_score     * 0.08 +
        relatability_score * 0.10
    )

    # ── Content type ───────────────────────────────────────────────────────────
    content_type = _classify_type(
        hook_in_opening, conflict_hits, humor_words_found,
        revelation_words_found, educational_hits, personal_hits,
        relatability_hits, has_cliffhanger
    )

    # ── Hook time ─────────────────────────────────────────────────────────────
    hook_time = _find_hook_time(w_in, start_s)

    # ── Reasons ───────────────────────────────────────────────────────────────
    reasons = _build_reasons(
        hook_hits, hook_in_opening, emotion_hits, conflict_hits,
        revelation_words_found, humor_words_found, relatability_hits,
        has_setup, has_escalation, has_payoff, has_cliffhanger,
        hook_strength, emotion_score, educational_hits, personal_hits,
        lang=lang,
    )

    return {
        "emotion_score":      round(emotion_score, 3),
        "hook_strength":      round(hook_strength, 3),
        "semantic_interest":  round(semantic_interest, 3),
        "standalone_value":   round(standalone_value, 3),
        "conflict_score":     round(conflict_score, 3),
        "humor_score":        round(humor_score, 3),
        "revelation_score":   round(revelation_score, 3),
        "shareability":       round(shareability, 3),
        "relatability_score": round(relatability_score, 3),
        "educational_score":  round(min(1.0, educational_hits * 0.25), 3),
        "content_type":       content_type,
        "story_structure": {
            "has_setup":       has_setup,
            "has_escalation":  has_escalation,
            "has_payoff":      has_payoff,
            "has_cliffhanger": has_cliffhanger,
        },
        "hook_time": round(hook_time, 2),
        "reasons":   reasons,
        "lang":      lang,
    }


def _classify_type(hook_in_opening, conflict_hits, humor_hits, revelation_hits,
                   educational_hits, personal_hits, relatability_hits,
                   has_cliffhanger) -> str:
    """Classify the dominant content type of a segment."""
    scores = {
        "hook":        hook_in_opening * 3 + (1 if has_cliffhanger else 0) * 2,
        "conflict":    conflict_hits * 2,
        "humor":       humor_hits * 2,
        "revelation":  revelation_hits * 2,
        "educational": educational_hits * 2,
        "story":       personal_hits,
        "relatable":   relatability_hits,
    }
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "other"


def _find_hook_time(words: list[dict], base_start: float) -> float:
    """Seconds from segment start until first high-interest word."""
    high_interest = {"!", "?", "wow", "wait", "omg", "oh", "no", "holy", "what",
                     "oye", "guau", "espera", "ay", "dios"}
    for w in words:
        wl = w["word"].lower().strip(".,!?\"'")
        if wl in high_interest or "!" in w["word"] or "?" in w["word"]:
            return max(0.0, w["start"] - base_start)
        if any(p.startswith(wl) for p in HOOK_PHRASES[:20]):
            return max(0.0, w["start"] - base_start)
    return max(0.0, (words[-1]["start"] - base_start) * 0.5) if words else 0.0


def _build_reasons(hook_hits, hook_in_opening, emotion_hits, conflict_hits,
                   revelation_hits, humor_hits, relatability_hits,
                   has_setup, has_escalation, has_payoff, has_cliffhanger,
                   hook_strength, emotion_score, educational_hits, personal_hits,
                   lang="en") -> list[str]:
    reasons = []
    if hook_in_opening >= 1:
        reasons.append("Strong opening hook")
    elif hook_hits >= 2:
        reasons.append("Multiple hook phrases")
    elif hook_hits == 1:
        reasons.append("Hook phrase detected")

    if "excitement" in emotion_hits:
        reasons.append("High excitement energy")
    if "surprise" in emotion_hits:
        reasons.append("Surprise/shock moment")
    if "tension" in emotion_hits:
        reasons.append("Tension and stakes")
    if "humor" in emotion_hits or humor_hits:
        reasons.append("Humor detected")
    if "anger" in emotion_hits:
        reasons.append("Emotional confrontation")
    if "revelation" in emotion_hits or revelation_hits:
        reasons.append("Revelation or discovery")
    if "inspiration" in emotion_hits:
        reasons.append("Inspirational content")
    if "relatability" in emotion_hits or relatability_hits:
        reasons.append("Highly relatable")

    if conflict_hits >= 2:
        reasons.append("High conflict engagement")
    elif conflict_hits == 1:
        reasons.append("Conflict present")

    if educational_hits >= 2:
        reasons.append("Strong educational value")
    elif educational_hits == 1:
        reasons.append("Educational content")

    if personal_hits >= 2:
        reasons.append("Personal narrative")

    if has_cliffhanger:
        reasons.append("Cliffhanger moment")

    if has_setup and has_payoff:
        reasons.append("Complete story arc")
    elif has_setup and has_escalation:
        reasons.append("Setup + escalation")
    elif has_payoff:
        reasons.append("Strong payoff")

    if hook_strength > 0.7:
        reasons.append("Exceptional hook strength")
    if emotion_score > 0.6:
        reasons.append("High emotional intensity")

    if lang == "es":
        reasons = [_REASON_TRANSLATIONS_ES.get(r, r) for r in reasons]
    return reasons[:7]


def _empty_result(start_s: float) -> dict:
    return {
        "emotion_score": 0.0, "hook_strength": 0.0, "semantic_interest": 0.0,
        "standalone_value": 0.5, "conflict_score": 0.0, "humor_score": 0.0,
        "revelation_score": 0.0, "shareability": 0.0, "relatability_score": 0.0,
        "educational_score": 0.0, "content_type": "other",
        "story_structure": {
            "has_setup": False, "has_escalation": False,
            "has_payoff": False, "has_cliffhanger": False,
        },
        "hook_time": 0.0, "reasons": [],
    }


# ── Smart boundary detection ───────────────────────────────────────────────────

def find_smart_start(words: list[dict], target_time: float, window_s: float = 12.0) -> float:
    """Find a natural start within [target_time - window_s, target_time + window_s/2]."""
    lo = target_time - window_s
    hi = target_time + window_s / 2

    candidates_in = [w for w in words if lo <= w["start"] <= hi]
    if not candidates_in:
        return target_time

    best = target_time
    best_score = -1.0

    for i, w in enumerate(candidates_in):
        score = 0.0
        wl = w["word"].lower().strip(".,!?\"'")

        if wl not in STANDALONE_PENALTY_STARTERS:
            score += 0.4

        if i > 0:
            prev_end = candidates_in[i - 1]["end"]
            pause = w["start"] - prev_end
            if pause >= 0.5:
                score += 0.5
            elif pause >= 0.25:
                score += 0.25

        if i == 0 or (i > 0 and any(candidates_in[i-1]["word"].endswith(p) for p in [".", "!", "?"])):
            score += 0.3

        if any(wl in p for p in HOOK_PHRASES[:20]):
            score += 0.4

        if wl in {"what", "why", "how", "when", "where", "who", "did", "have", "can"}:
            score += 0.2

        distance_penalty = abs(w["start"] - target_time) / window_s * 0.3
        score -= distance_penalty

        if score > best_score:
            best_score = score
            best = w["start"]

    return round(best, 3)


def find_smart_end(words: list[dict], target_time: float, window_s: float = 12.0) -> float:
    """Find a natural end within [target_time - window_s/2, target_time + window_s]."""
    lo = target_time - window_s / 2
    hi = target_time + window_s

    candidates_in = [w for w in words if lo <= w["end"] <= hi]
    if not candidates_in:
        return target_time

    best = target_time
    best_score = -1.0

    for i, w in enumerate(candidates_in):
        score = 0.0
        word_text = w["word"]

        if word_text.endswith((".", "!", "?")):
            score += 0.6
        elif word_text.endswith((",", ";", ":")):
            score += 0.2

        if i + 1 < len(candidates_in):
            next_start = candidates_in[i + 1]["start"]
            pause = next_start - w["end"]
            if pause >= 0.5:
                score += 0.5
            elif pause >= 0.25:
                score += 0.25

        payoff_closers = [
            "finally", "exactly", "right", "seriously", "unbelievable",
            "insane", "crazy", "incredible", "period", "forever",
            "everything", "nothing", "always", "never", "anymore",
        ]
        if any(p in word_text.lower() for p in payoff_closers):
            score += 0.3

        distance_penalty = abs(w["end"] - target_time) / window_s * 0.3
        score -= distance_penalty

        if score > best_score:
            best_score = score
            best = w["end"]

    return round(best, 3)


# ── Retention score ────────────────────────────────────────────────────────────

def compute_retention_score(words: list[dict], start_s: float, end_s: float) -> dict:
    """Compute retention-related metrics for a segment."""
    w_in = [w for w in words if w["start"] >= start_s - 0.1 and w["end"] <= end_s + 0.1]
    duration = max(end_s - start_s, 1.0)

    if not w_in:
        return {"retention_score": 0.4, "hook_time": duration / 2, "pacing": 0.0,
                "dead_air_ratio": 1.0, "progression": 0.3}

    # Pacing: words per second (ideal ~2.0–3.5)
    wps = len(w_in) / duration
    if 2.0 <= wps <= 3.5:
        pacing_score = 1.0
    elif wps < 2.0:
        pacing_score = max(0.2, wps / 2.0)
    else:
        pacing_score = max(0.5, 1.0 - (wps - 3.5) / 5.0)

    # Dead air
    spoken_duration = sum(max(0, w["end"] - w["start"]) for w in w_in)
    dead_air_ratio = max(0.0, 1.0 - spoken_duration / duration)
    dead_air_score = max(0.0, 1.0 - dead_air_ratio * 1.5)

    # Hook time
    sem = analyze_segment(w_in, start_s, end_s)
    hook_time = sem["hook_time"]
    hook_time_score = max(0.0, 1.0 - hook_time / 10.0)

    # Content density
    content_density = min(1.0, (
        sem["hook_strength"]    * 0.3 +
        sem["emotion_score"]    * 0.3 +
        sem["semantic_interest"] * 0.4
    ))

    # Progression: first vs second half, reward escalation
    mid = start_s + duration / 2
    first_half = [w for w in w_in if w["start"] < mid]
    second_half = [w for w in w_in if w["start"] >= mid]
    s1 = analyze_segment(first_half, start_s, mid) if first_half else _empty_result(start_s)
    s2 = analyze_segment(second_half, mid, end_s) if second_half else _empty_result(mid)
    avg_interest = (s1["semantic_interest"] + s2["semantic_interest"]) / 2
    escalation_bonus = max(0.0, (s2["semantic_interest"] - s1["semantic_interest"]) * 0.1)
    progression_score = min(1.0, avg_interest + 0.15 + escalation_bonus)

    retention_score = (
        hook_time_score   * 0.25 +
        pacing_score      * 0.20 +
        dead_air_score    * 0.15 +
        progression_score * 0.20 +
        content_density   * 0.20
    )

    return {
        "retention_score": round(min(1.0, retention_score), 3),
        "hook_time":       round(hook_time, 2),
        "pacing":          round(pacing_score, 3),
        "dead_air_ratio":  round(dead_air_ratio, 3),
        "progression":     round(progression_score, 3),
    }
