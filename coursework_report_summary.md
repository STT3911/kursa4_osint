# Coursework Report Summary

## Dataset Overview

- Total profiles: 4959
- Profiles with bio: 1955
- Profiles with username: 3812
- Profiles with photo: 3195

## OSINT Part

The OSINT subsystem collects public Telegram profiles, stores user-to-group links,
exports datasets, and enriches usernames through Sherlock, optional Snoop, and manual Maigret checks. Each profile receives
an `osint_score` and an `exposure_level` based on available identifiers, profile
text, photos, group presence, and external account findings.

Top Telegram groups:
- andrewgiftschat: 2550
- rabota_chaty1: 1048
- laravel_pro: 1000
- tproger_chat: 221
- python_ru: 114

OSINT score distribution:
- 0-24: 996
- 25-49: 2088
- 50-74: 1875
- 75-100: 0

Exposure level distribution:
- low: 3021
- medium: 1176
- high: 762

Top profiles by OSINT score:
- @AniCoder: score 70, high
- @khudyakv: score 70, high
- @nomogger: score 70, high
- @zxccazi: score 70, high
- @anton_leon_web: score 70, high

Group coverage:
- andrewgiftschat: users 2550, usernames 2366, bios 1396
- rabota_chaty1: users 1048, usernames 257, bios 120
- laravel_pro: users 1000, usernames 911, bios 320
- tproger_chat: users 221, usernames 172, bios 64
- python_ru: users 114, usernames 81, bios 35

## NLP and Analytics Part

The NLP subsystem searches profiles by semantic similarity over `bio` text and
uses the enriched dataset for hybrid ranking. The AI subsystem classifies
profiles into professional directions, supports a trained classifier stored in
`models/profile_classifier.joblib`, and falls back to explainable keyword rules
when the trained model is not available. The analytics tab visualizes data
quality and helps explain whether the dataset is suitable for semantic
retrieval and classification experiments.

Bio length distribution:
- 0: 3004
- 1-40: 1050
- 41-120: 861
- 121+: 44

## Demonstration

1. Open the desktop application.
2. Show the analytics tab and dataset quality charts.
3. Run a semantic query such as `python backend`.
4. Open a profile card and explain the relevance score.
5. Show the OSINT score, exposure level, score breakdown, and Sherlock/Maigret checks.
6. Open the OSINT analysis tab and show top profiles and group coverage.
7. Export the enriched dataset, OSINT report, and profile report.
