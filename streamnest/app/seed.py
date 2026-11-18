"""Create six original, synthetic demo clips. Never run against production data."""
import os
import secrets
import shutil
import subprocess
import uuid
from pathlib import Path

from app.main import DATA, MEDIA, PRODUCTION, connect, init_db, now, ph, process_video

CLIPS = [
    ("Gaming", "Gaming: Neue Welten entdecken", "YOUR NEXT LEVEL", "5b3d95"),
    ("Technologie", "Technologie: Ideen für morgen", "THINK DIFFERENTLY", "236678"),
    ("Musik", "Musik: Finde deinen Rhythmus", "FEEL THE RHYTHM", "8b447d"),
    ("Kreativ", "Kreativ: Mach etwas Eigenes", "MAKE SOMETHING", "a46142"),
    ("Wissen", "Wissen: Bleib neugierig", "STAY CURIOUS", "4f7350"),
    ("Lifestyle", "Lifestyle: Kleine Momente, grosse Ideen", "ENJOY THE MOMENT", "80516b"),
]

def main():
    if PRODUCTION:
        raise SystemExit("Demo-Seeding ist in Produktion absichtlich gesperrt.")
    init_db()
    db = connect()
    try:
        if db.execute("SELECT 1 FROM users WHERE username='studio_demo'").fetchone():
            print("Demokanal existiert bereits. Keine Daten geändert.")
            return
        password = os.getenv("DEMO_PASSWORD") or secrets.token_urlsafe(18)
        if len(password) < 12:
            raise SystemExit("DEMO_PASSWORD benötigt mindestens 12 Zeichen.")
        with db:
            uid = db.execute(
                "INSERT INTO users(username,email,password_hash,display_name,bio,created_at) VALUES(?,?,?,?,?,?)",
                ("studio_demo", "demo@example.invalid", ph.hash(password), "Streamly Studio",
                 "Willkommen im Demo-Studio. Alle Videos sind eigens generierte, synthetische Beispielclips – keine echten Creator-Inhalte.", now())).lastrowid
        font = next((str(p) for p in [
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
            Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"),
            Path("C:/Windows/Fonts/arialbd.ttf")
        ] if p.exists()), None)
        for index, (category, title, caption, color) in enumerate(CLIPS):
            vid = uuid.uuid4().hex
            source, target, poster = MEDIA / f"{vid}.part", MEDIA / f"{vid}.mp4", MEDIA / f"{vid}.jpg"
            font_option = f"fontfile='{font}':" if font else ""
            # These are deliberately original graphical clips, not copyrighted sample footage.
            filters = (
                f"drawgrid=width=60:height=60:thickness=1:color=white@0.06,"
                f"drawbox=x=680:y=80:w=400:h=400:color=white@0.07:t=2,"
                f"drawbox=x=740:y=140:w=280:h=280:color=white@0.12:t=2,"
                f"drawbox=x=800:y=200:w=160:h=160:color=white@0.2:t=fill,"
                f"drawtext={font_option}text='STREAMLY STUDIO':fontcolor=0xc7f563:fontsize=20:x=60:y=90,"
                f"drawtext={font_option}text='{caption}':fontcolor=white:fontsize=42:x=60:y=235,"
                f"drawtext={font_option}text='ORIGINAL DEMO CLIP   /   0{index+1}':fontcolor=white@0.65:fontsize=16:x=60:y=420,"
                f"drawbox=x=0:y=530:w=1280:h=10:color=0xc7f563@0.3:t=fill"
            )
            try:
                subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi",
                                "-i", f"color=c=0x{color}:s=1280x720:r=24",
                                "-f", "lavfi", "-i", f"sine=frequency={220+index*55}:sample_rate=44100",
                                "-vf", filters, "-af", "volume=0.025,afade=t=in:d=1,afade=t=out:st=7:d=1",
                                "-t", "8", "-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
                                "-pix_fmt", "yuv420p", "-c:a", "aac", "-f", "mp4", "-y", str(source)],
                               check=True, capture_output=True, timeout=90)
                length = process_video(source, ".mp4", target, poster)
                with db:
                    db.execute(
                        "INSERT INTO videos(id,user_id,title,description,category,filename,poster,duration,size,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (vid, uid, title + " (Demo)", "Dies ist ein synthetischer, mit FFmpeg erzeugter Demo-Clip zur Funktionsprüfung von Streamly. Er enthält keine echten Aufnahmen. Alle Statistiken starten bei null.",
                         category, target.name, poster.name, length, target.stat().st_size, now() - index * 3600))
                print(f"Erstellt: {title}")
            finally:
                source.unlink(missing_ok=True)
        print("\nDemo eingerichtet. Benutzername: studio_demo")
        print("Einmaliges Passwort:", password)
        print("Kein Standardpasswort. Bewahre es nur für deine lokale Demo auf.")
    finally:
        db.close()

if __name__ == "__main__":
    main()
