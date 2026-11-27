"""Style bible + the verified episode-1 material for the explainer room.

Source of truth for the example problem (verified 27 Nov 2026 against the
material Tuan actually used on 25 Nov 2026 — the 6 keyframes in
~/workspace/satu-soal-tiga-cara/ and the narration script in
~/workspace/satu-soal-tiga-cara/build-narration.sh):

- Format: "Satu Soal, Tiga Cara" — one maths problem, three solution methods,
  vertical 9:16, ~60 s, hand-drawn stickman style.
- Characters: Doni (orange stickman, small hat), Dina (blue stickman, two
  pigtails), pink candies, off-white paper background.
- Episode 1 problem: Doni and Dina share 5 candies; Doni has 1 more than
  Dina. System: x + y = 5, x - y = 1. Solution: Doni x = 3, Dina y = 2.
- The three methods are substitusi, eliminasi, MATRIKS — not grafik. (The
  25 Nov material is explicit: scenes 3/4/5 are substitusi/eliminasi/matriks,
  and the narration for scene 5 says "Cara tiga, matriks".) Do not swap the
  third method for a graph without Tuan's say-so.

The narration strings below are verbatim the lines Tuan recorded on 25 Nov
(total 63.3 s, slightly over the 60 s target — that trim decision is still
pending with Tuan; the room keeps the lines as-is).
"""

from __future__ import annotations

# ---------------------------------------------------------------- style
PAPER = (253, 246, 227)      # off-white paper background
INK = (43, 43, 43)           # near-black line art
DONI = (232, 116, 28)        # Doni: orange
DINA = (52, 110, 199)        # Dina: blue
CANDY = (244, 130, 178)      # pink candy
BOARD_BG = (255, 255, 255)
BOARD_BORDER = (43, 43, 43)
ACCENT = (34, 139, 92)       # green check / result highlight

FRAME_SIZE = (720, 1280)     # 9:16 vertical Short
TITLE = "Satu Soal, Tiga Cara"

# ---------------------------------------------------------------- characters
CHARACTERS = {
    "doni": {"name": "Doni", "color": DONI, "hat": True, "pigtails": False},
    "dina": {"name": "Dina", "color": DINA, "hat": False, "pigtails": True},
}

# ---------------------------------------------------------------- the problem
# x = permen Doni, y = permen Dina. x + y = 5, x - y = 1 -> x = 3, y = 2.
SAMPLE_SYSTEM = {
    "a": 1, "b": 1, "c": 5,      # x + y = 5
    "d": 1, "e": -1, "f": 1,     # x - y = 1
    "x_name": "Doni",
    "y_name": "Dina",
    "x_label": "x",
    "y_label": "y",
}
SAMPLE_SOLUTION = {"x": 3, "y": 2}

PROBLEM_TEXT = (
    "Doni dan Dina punya permen, totalnya lima. "
    "Doni punya satu lebih banyak dari Dina. "
    "Berapa permen mereka masing-masing?"
)

# ---------------------------------------------------------------- narration (verbatim, 25 Nov 2026)
NARRATION = [
    "Aljabar linear kelihatan ngeri? Padahal ini cuma soal bagi permen. Satu soal, tiga cara. Simak!",
    "Doni dan Dina punya permen, totalnya lima. Doni punya satu lebih banyak dari Dina. Berapa permen mereka masing-masing? Dalam matematika, ini ditulis: x tambah y sama dengan lima, x kurang y sama dengan satu.",
    "Cara satu, substitusi. Anggap Doni itu Dina ditambah satu. Lalu masukkan ke total. Dina tambah satu, tambah Dina, sama dengan lima. Jadi dua Dina sama dengan empat. Dina punya dua permen!",
    "Cara dua, eliminasi. Jumlahkan kedua informasi. Dina yang tambah dan Dina yang kurang saling menghapus! Tinggal dua Doni sama dengan enam. Jadi Doni punya tiga permen!",
    "Cara tiga, matriks. Rapikan semuanya jadi tabel angka. Kurangi baris bawah dengan baris atas. Ketemu: Dina dua, Doni tiga. Cara ini favorit komputer, karena rapi dan bisa untuk ribuan variabel!",
    "Tiga cara, satu jawaban: Doni tiga, Dina dua. Matematika rumit itu cuma butuh analogi yang pas. Mau topik apa selanjutnya? Tulis di komentar!",
]

# ---------------------------------------------------------------- scenes
# kind: hook | soal | substitusi | eliminasi | matriks | kesimpulan
# board: lines drawn on the whiteboard; candies: (who, count) piles shown.
SCENES = [
    {
        "kind": "hook",
        "title": "Hook",
        "narration": NARRATION[0],
        "board": ["Satu soal,", "tiga cara!", "x + y = ?"],
        "candies": [],
        "characters": ["doni", "dina"],
    },
    {
        "kind": "soal",
        "title": "Soalnya",
        "narration": NARRATION[1],
        "board": ["x + y = 5", "x - y = 1", "x = Doni, y = Dina"],
        "candies": [("doni", 3), ("dina", 2)],
        "characters": ["doni", "dina"],
    },
    {
        "kind": "substitusi",
        "title": "Cara 1: Substitusi",
        "narration": NARRATION[2],
        "board": ["x = y + 1", "2y = 4", "y = 2"],
        "candies": [("dina", 2)],
        "characters": ["doni", "dina"],
    },
    {
        "kind": "eliminasi",
        "title": "Cara 2: Eliminasi",
        "narration": NARRATION[3],
        "board": ["(x + y) + (x - y) = 5 + 1", "2x = 6", "x = 3"],
        "candies": [("doni", 3)],
        "characters": ["doni", "dina"],
    },
    {
        "kind": "matriks",
        "title": "Cara 3: Matriks",
        "narration": NARRATION[4],
        "board": ["[1  1 | 5]", "[1 -1 | 1]", "R2 - R1 -> y = 2, x = 3"],
        "candies": [],
        "characters": ["doni", "dina"],
    },
    {
        "kind": "kesimpulan",
        "title": "Kesimpulan",
        "narration": NARRATION[5],
        "board": ["Doni = 3", "Dina = 2", "3 cara, 1 jawaban!"],
        "candies": [("doni", 3), ("dina", 2)],
        "characters": ["doni", "dina"],
    },
]
