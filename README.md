# SportEquity — AI-Powered Sports Inclusion Platform

An end-to-end Flask + MongoDB web application connecting **athletes, trainers, doctors,
and community admins** with AI analytics, health tracking, QR digital IDs, and
role-based dashboards.

---

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure environment (copy and edit)
cp .env.example .env      # or just edit .env directly

# 3. Run the app
python app.py

# 4. Load demo data (first time only)
open http://localhost:5000/seed-demo-data

# 5. Login with any demo account
open http://localhost:5000/login
```

---

## Demo Accounts

| Role | Email | Password |
|------|-------|----------|
| Athlete | athlete@sportequity.com | password123 |
| Trainer | trainer@sportequity.com | password123 |
| Doctor | doctor@sportequity.com | password123 |
| Admin | admin@sportequity.com | password123 |

---

## Configuration (`.env`)

| Variable | Required | Description |
|----------|----------|-------------|
| `SECRET_KEY` | Yes | Flask session secret (change in production) |
| `MONGO_URI` | No | MongoDB Atlas connection string. Falls back to `localhost:27017`, then in-memory mock |
| `GROQ_API_KEY` | No | Enables AI chatbot via Groq LLM. Falls back to rule-based responses |

---

## Features by Role

### 🏃 Athlete
- Digital profile with QR ID card (scan to view public profile)
- Log training sessions, health records, and diet
- SportScore AI rating (performance × health × training × diet formula)
- Performance trend charts (Chart.js)
- Diet analysis with recommendations
- Book appointments with trainers or doctors
- AI chatbot (Groq or rule-based fallback)
- Emergency alert button

### 💪 Trainer
- View all athletes with SportScore ratings
- See appointments booked with you
- Create tournaments
- Browse all tournaments

### 🩺 Doctor
- View all athlete health records with BMI/heart-rate indicators
- See appointments booked with you
- View active emergency alerts

### 🛡️ Community Admin
- Register rural athletes (no device required)
- Verify / unverify athletes
- Edit athlete profiles and stats
- Create tournaments for the region
- View region statistics

---

## Project Structure

```
sportequity/
├── app.py                  # ALL backend — routes, DB, analytics, AI, QR
├── requirements.txt
├── .env                    # Your local config (not committed)
├── templates/
│   ├── base.html           # Navbar, flash messages, footer
│   ├── index.html          # Landing page
│   ├── login.html
│   ├── register.html
│   ├── athlete_dashboard.html
│   ├── trainer_dashboard.html
│   ├── doctor_dashboard.html
│   ├── admin_dashboard.html
│   ├── admin_statistics.html
│   ├── athlete_profile.html  # Edit + public view
│   ├── id_card.html
│   ├── appointments.html
│   ├── training_log.html
│   ├── health_log.html
│   ├── diet_log.html
│   ├── tournament_finder.html
│   ├── chatbot.html
│   ├── 404.html
│   └── 500.html
└── static/
    ├── css/style.css
    └── js/main.js
```

---

## SportScore Formula

```
SportScore = (Performance × 0.4) + (Health × 0.2) + (Training × 0.3) + (Diet × 0.1)
```

- **Performance** — average training intensity × 1.25 (capped at 100)
- **Health** — starts at 100, deducted for high BMI or blood pressure
- **Training** — unique months of activity × 10 (capped at 100)
- **Diet** — 100 if avg daily calories 1800–2500, else 70

---

## Running Without MongoDB

The app detects when MongoDB is unavailable and automatically switches to an
**in-memory mock database**. All features work — data just resets on restart.
This is ideal for demos and testing.

---

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/athlete/<id>/analytics` | Training, health & diet chart data |
| `GET /api/athlete/<id>/diet-analysis` | Diet insights and recommendations |
| `POST /athlete/chatbot` | AI chatbot (JSON: `{"question":"..."}`) |
| `POST /athlete/emergency` | Trigger emergency alert |
| `GET /seed-demo-data` | Load demo data (resets all data) |

