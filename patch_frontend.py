import os

def fix_app_js():
    path = os.path.join("frontend", "assets", "app.js")
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # Exact strings
    replacements = [
        ("'pending'", "'SCRAPED'"),
        ('"pending"', '"SCRAPED"'),
        (".pending", ".SCRAPED"),
        ("stage=pending", "stage=SCRAPED"),
        ("stageKey:'pending'", "stageKey:'SCRAPED'"),
        
        ("'approved'", "'REVIEWED'"),
        ('"approved"', '"REVIEWED"'),
        (".approved", ".REVIEWED"),
        ("stage=approved", "stage=REVIEWED"),
        ("stageKey:'approved'", "stageKey:'REVIEWED'"),
        
        ("'text_edit'", "'ENRICHED'"),
        ('"text_edit"', '"ENRICHED"'),
        (".text_edit", ".ENRICHED"),
        ("stage=text_edit", "stage=ENRICHED"),
        
        ("'posted'", "'LIVE'"),
        ('"posted"', '"LIVE"'),
        (".posted", ".LIVE"),
        ("stage=posted", "stage=LIVE"),
        ("stageKey:'posted'", "stageKey:'LIVE'"),
        
        ("'rejected'", "'REJECTED'"),
        ('"rejected"', '"REJECTED"'),
        (".rejected", ".REJECTED"),
        ("stage=rejected", "stage=REJECTED"),
        ("stageKey:'rejected'", "stageKey:'REJECTED'"),
        
        # specific fixes for avg_margin/avg_score
        ("stats.avg_margin_SCRAPED", "stats.avg_margin_pending"),
        ("stats.avg_score_SCRAPED", "stats.avg_score_pending"),
        ("s.avg_margin_SCRAPED", "s.avg_margin_pending"),
        ("s.avg_score_SCRAPED", "s.avg_score_pending"),
    ]

    for old, new in replacements:
        content = content.replace(old, new)

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    
    print("Done applying band-aid to app.js")

if __name__ == "__main__":
    fix_app_js()
