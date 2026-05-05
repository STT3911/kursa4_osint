# Summary Report

## Dataset Overview

- Total profiles: 300
- Profiles with bio: 159
- Profiles with username: 287
- Profiles with photo: 247

## OSINT Part

The OSINT subsystem collects public Telegram profiles, stores user-to-group links,
exports datasets, and enriches usernames through Sherlock and optional Snoop. Each profile receives
an `osint_score` and an `exposure_level` based on available identifiers, profile
text, photos, group presence, and external account findings.

Top Telegram groups:
- andrewgiftschat: 300

OSINT score distribution:
- 0-24: 7
- 25-49: 98
- 50-74: 154
- 75-100: 41

Exposure level distribution:
- low: 101
- medium: 85
- high: 114

Top profiles by OSINT score:
- @huuir: score 100, high
- @kozak85: score 100, high
- @uzacx: score 95, high
- @yazykidlyy: score 95, high
- @pzzdd4x: score 95, high

Group coverage:
- andrewgiftschat: users 300, usernames 287, bios 159

## NLP and Analytics Part

The NLP subsystem searches profiles by semantic similarity over `bio` text and
uses the enriched dataset for hybrid ranking. The AI subsystem classifies
profiles into professional directions, supports a trained classifier stored in
`models/profile_classifier.joblib`, and falls back to explainable keyword rules
when the trained model is not available. The analytics tab visualizes data
quality and helps explain whether the dataset is suitable for semantic
retrieval and classification experiments.

Bio length distribution:
- 0: 141
- 1-40: 84
- 41-120: 71
- 121+: 4

## Demonstration

1. Open the desktop application.
2. Show the analytics tab and dataset quality charts.
3. Run a semantic query such as `python backend`.
4. Open a profile card and explain the relevance score.
5. Show the OSINT score, exposure level, score breakdown, and Sherlock check.
6. Open the OSINT analysis tab and show top profiles and group coverage.
7. Export the enriched dataset, OSINT report, and profile report.
