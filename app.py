"""
SportEquity - AI-powered sports inclusion platform
Fixed version: all identified bugs resolved
"""

import os
import json
import qrcode
import hashlib
import secrets
from datetime import datetime, timedelta
from io import BytesIO
import base64
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from pymongo import MongoClient
from bson.objectid import ObjectId
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'sportequity-dev-secret-2024')

# ─── Optional Groq ───────────────────────────────────────────────────────────
try:
    from groq import Groq
    groq_api_key = os.getenv('GROQ_API_KEY')
    groq_client = Groq(api_key=groq_api_key) if groq_api_key else None
except ImportError:
    groq_client = None

# ─── MongoDB ─────────────────────────────────────────────────────────────────
MONGO_URI = os.getenv('MONGO_URI', 'mongodb+srv://username:password@cluster.mongodb.net/')
db = None

def connect_mongo():
    global db
    for uri in [MONGO_URI, 'mongodb://localhost:27017/']:
        try:
            c = MongoClient(uri, serverSelectionTimeoutMS=4000)
            c.admin.command('ping')
            db = c['sportequity']
            print(f"Connected to MongoDB: {uri[:40]}...")
            return True
        except:
            pass
    print("WARNING: MongoDB unavailable – using in-memory mock")
    return False

connect_mongo()

# ─── In-memory mock DB ────────────────────────────────────────────────────────
_stores = {n: {} for n in ['users','athletes','training_logs','health_records',
                            'diet_logs','appointments','tournaments','ai_chats','emergencies']}
_id_seq = [9000]

def _nid():
    _id_seq[0] += 1
    return str(_id_seq[0])

class MockCursor(list):
    def sort(self, *a, **k): return self
    def limit(self, n): return MockCursor(self[:n])

class MockCol:
    def __init__(self, store): self._s = store

    def find_one(self, q=None):
        for doc in self._s.values():
            if self._matches(doc, q or {}):
                return doc
        return None

    def find(self, q=None):
        return MockCursor([d for d in self._s.values() if self._matches(d, q or {})])

    def _matches(self, doc, q):
        for k, v in q.items():
            if k == '$or':
                if not any(self._matches(doc, sub) for sub in v):
                    return False
            else:
                if str(doc.get(k,'')) != str(v):
                    return False
        return True

    def insert_one(self, doc):
        oid = doc.get('_id') or _nid()
        doc['_id'] = oid
        self._s[str(oid)] = doc
        class R: inserted_id = oid
        return R()

    def insert_many(self, docs):
        ids = []
        for d in docs:
            ids.append(self.insert_one(d).inserted_id)
        class R: inserted_ids = ids
        return R()

    def update_one(self, q, upd, upsert=False):
        doc = self.find_one(q)
        if doc:
            if '$set' in upd: doc.update(upd['$set'])
            if '$push' in upd:
                for k, v in upd['$push'].items(): doc.setdefault(k, []).append(v)
        elif upsert:
            nd = dict(q)
            if '$set' in upd: nd.update(upd['$set'])
            self.insert_one(nd)

    def delete_many(self, q):
        if not q:
            self._s.clear()
        else:
            for k in list(self._s.keys()):
                if self._matches(self._s[k], q):
                    del self._s[k]

    def count_documents(self, q=None):
        return len(self.find(q or {}))

class MockDB:
    def __init__(self):
        self._cols = {n: MockCol(s) for n, s in _stores.items()}
    def __getitem__(self, name):
        if name not in self._cols:
            _stores[name] = {}
            self._cols[name] = MockCol(_stores[name])
        return self._cols[name]
    def __getattr__(self, name): return self[name]

if db is None:
    db = MockDB()

def get_col(name):
    try: return db[name]
    except: return getattr(db, name)

# ─── Utility ──────────────────────────────────────────────────────────────────
def hash_password(pwd):
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac('sha256', pwd.encode(), salt.encode(), 100000).hex()
    return f"{salt}${h}"

def verify_password(stored, provided):
    try:
        salt, h = stored.split('$', 1)
        return hashlib.pbkdf2_hmac('sha256', provided.encode(), salt.encode(), 100000).hex() == h
    except:
        return False

def oid(val):
    try: return ObjectId(str(val))
    except: return str(val)

def sid(val):
    return str(val)

def login_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return wrapped

def role_required(roles):
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if 'user_id' not in session:
                return redirect(url_for('login'))
            user = get_col('users').find_one({'_id': oid(session['user_id'])})
            if not user or user.get('role') not in roles:
                flash('Access denied.', 'danger')
                return redirect(url_for('dashboard'))
            return f(*args, **kwargs)
        return wrapped
    return decorator

def generate_qr_code(data):
    qr = qrcode.QRCode(version=1, box_size=8, border=4)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color='black', back_color='white')
    buf = BytesIO(); img.save(buf,'PNG'); buf.seek(0)
    return base64.b64encode(buf.getvalue()).decode()

# ─── Analytics ────────────────────────────────────────────────────────────────
def calculate_sport_score(athlete_id):
    try:
        aid = oid(athlete_id)
        t = list(get_col('training_logs').find({'athlete_id': aid}))
        h = list(get_col('health_records').find({'athlete_id': aid}))
        d = list(get_col('diet_logs').find({'athlete_id': aid}))
        perf = min(100, (sum(int(l.get('intensity',0)) for l in t)/len(t)*1.25)) if t else 0
        health = 100
        if h:
            last = h[-1]
            if float(last.get('bmi',0) or 0) > 30: health -= 20
            try:
                if int(str(last.get('blood_pressure','0/0')).split('/')[0]) > 140: health -= 15
            except: pass
        else: health = 70
        training = min(100, len(set(l.get('date','')[:7] for l in t))*10) if t else 0
        avg_cal = sum(int(l.get('calories',0)) for l in d[-7:])/len(d[-7:]) if d else 0
        diet = 100 if 1800 <= avg_cal <= 2500 else 70
        return round(perf*0.4 + health*0.2 + training*0.3 + diet*0.1, 2)
    except Exception as e:
        print(f"sport_score err: {e}"); return 0

def analyze_performance(athlete_id):
    try:
        aid = oid(athlete_id)
        logs = sorted(list(get_col('training_logs').find({'athlete_id': aid})),
                      key=lambda x: x.get('date',''), reverse=True)
        if len(logs) < 2:
            return {'improvement':'Not enough data','trend':'N/A','current_intensity':0,'sessions_logged':len(logs)}
        r = [int(l.get('intensity',0)) for l in logs[:7]]
        p = [int(l.get('intensity',0)) for l in logs[7:14]] or r
        ra = sum(r)/len(r); pa = sum(p)/len(p)
        pct = ((ra-pa)/pa*100) if pa else 0
        return {'improvement':f'{pct:+.1f}%','trend':'Improving' if pct>0 else ('Declining' if pct<0 else 'Stable'),
                'current_intensity':round(ra,1),'sessions_logged':len(logs)}
    except Exception as e:
        print(f"perf err: {e}")
        return {'improvement':'0%','trend':'N/A','current_intensity':0,'sessions_logged':0}

def analyze_diet(diet_logs):
    if not diet_logs: return {'status':['No diet data yet.'],'recommendations':[]}
    recent = diet_logs[-7:] if len(diet_logs)>7 else diet_logs
    ap = sum(int(l.get('protein',0)) for l in recent)/len(recent)
    ac = sum(int(l.get('calories',0)) for l in recent)/len(recent)
    aw = sum(int(l.get('water_intake',0)) for l in recent)/len(recent)
    s,r = [],[]
    if ap<50: s.append('Protein below 50g/day'); r.append('Add lean meats, eggs or legumes')
    else: s.append('Protein intake optimal')
    if aw<2000: s.append('Hydration insufficient (<2L)'); r.append('Drink 2–3L water daily')
    else: s.append('Hydration optimal')
    if 1800<=ac<=2500: s.append('Calorie intake optimal')
    elif ac<1800: s.append('Calories too low'); r.append('Increase intake for recovery')
    else: s.append('Calories high'); r.append('Monitor portions')
    return {'status':s,'recommendations':r}

def ai_chatbot_response(question):
    if groq_client:
        try:
            sys_p = ("You are SportEquity AI – expert sports coach. "
                     "Give concise, evidence-based advice in 2-3 sentences.")
            comp = groq_client.chat.completions.create(
                model='llama-3.3-70b-versatile', max_tokens=300,
                messages=[{'role':'system','content':sys_p},{'role':'user','content':question}])
            return comp.choices[0].message.content
        except: pass
    q = question.lower()
    if any(w in q for w in ['train','workout','exercise']): return 'Combine 3x strength + 2x cardio per week. Always warm up 10 minutes before sessions and progressively increase intensity each week.'
    if any(w in q for w in ['diet','eat','food','protein','calorie']): return 'Eat carbs + protein 2–3 hours before training. Consume 20–40g protein within 30 minutes post-workout for optimal recovery.'
    if any(w in q for w in ['injur','pain','hurt']): return 'For minor injuries: RICE (Rest, Ice, Compression, Elevation). If pain persists over 48 hours, consult your doctor immediately.'
    if any(w in q for w in ['sleep','rest','tired']): return 'Athletes need 8–10 hours of quality sleep. Keep a consistent schedule and avoid screens 1 hour before bed for deep sleep.'
    return "I'm SportEquity AI. Ask me about training, nutrition, injuries, or sleep recovery!"

# ─── Auth ─────────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('index.html')

@app.route('/register', methods=['GET','POST'])
def register():
    if request.method == 'POST':
        email    = request.form.get('email','').lower().strip()
        password = request.form.get('password','')
        name     = request.form.get('full_name','').strip()
        role     = request.form.get('role','athlete')
        region   = request.form.get('region','').strip()
        spec     = request.form.get('specialization','').strip()
        if not email or not password or not name:
            return render_template('register.html', error='All fields are required')
        if role == 'admin' and not region:
            return render_template('register.html', error='Region is required for Community Admin')
        if get_col('users').find_one({'email': email}):
            return render_template('register.html', error='Email already registered')
        res = get_col('users').insert_one({
            'email':email,'password':hash_password(password),'full_name':name,
            'role':role,'region':region,'specialization':spec,
            'created_at':datetime.now().isoformat()
        })
        uid = res.inserted_id
        if role == 'athlete':
            get_col('athletes').insert_one({
                'user_id':uid,'name':name,'email':email,'age':0,'gender':'',
                'sport':'','region':region,'bio':'','achievements':[],
                'profile_photo':'','visibility':'private','sport_score':0,
                'verified':False,'created_at':datetime.now().isoformat()
            })
        session['user_id'] = sid(uid)
        session['role']    = role
        session['full_name'] = name
        flash(f'Welcome, {name}!','success')
        return redirect(url_for('dashboard'))
    return render_template('register.html')

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        email    = request.form.get('email','').lower().strip()
        password = request.form.get('password','')
        user = get_col('users').find_one({'email':email})
        if user and verify_password(user['password'], password):
            session['user_id']   = sid(user['_id'])
            session['role']      = user.get('role','athlete')
            session['full_name'] = user.get('full_name','')
            return redirect(url_for('dashboard'))
        return render_template('login.html', error='Invalid email or password')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ─── Dashboard ────────────────────────────────────────────────────────────────
@app.route('/dashboard')
@login_required
def dashboard():
    return redirect(url_for({'athlete':'athlete_dashboard','trainer':'trainer_dashboard',
        'doctor':'doctor_dashboard','admin':'admin_dashboard'}.get(session.get('role','athlete'),'athlete_dashboard')))

# ─── Athlete Dashboard ────────────────────────────────────────────────────────
@app.route('/athlete/dashboard')
@login_required
def athlete_dashboard():
    uid     = session['user_id']
    athlete = get_col('athletes').find_one({'user_id':oid(uid)})
    if not athlete: return redirect(url_for('athlete_profile'))
    aid = athlete['_id']
    t = sorted(list(get_col('training_logs').find({'athlete_id':aid})), key=lambda x:x.get('date',''), reverse=True)
    h = sorted(list(get_col('health_records').find({'athlete_id':aid})), key=lambda x:x.get('date',''), reverse=True)
    d = sorted(list(get_col('diet_logs').find({'athlete_id':aid})), key=lambda x:x.get('date',''), reverse=True)
    appts = list(get_col('appointments').find({'athlete_id':aid}))
    return render_template('athlete_dashboard.html',
        athlete=athlete, sport_score=calculate_sport_score(aid),
        performance=analyze_performance(aid),
        training_logs=t[:10], health_records=h[:1], diet_logs=d[:7],
        appointments=appts)

# ─── Trainer Dashboard ────────────────────────────────────────────────────────
@app.route('/trainer/dashboard')
@login_required
@role_required(['trainer'])
def trainer_dashboard():
    uid  = session['user_id']
    user = get_col('users').find_one({'_id':oid(uid)})
    athletes = list(get_col('athletes').find({}))
    total_sessions = get_col('training_logs').count_documents({})
    # Appointments for THIS trainer
    appts = list(get_col('appointments').find({'trainer_id':uid}))
    for a in appts:
        ath = get_col('athletes').find_one({'_id':a.get('athlete_id')})
        a['athlete_name'] = ath.get('name','?') if ath else '?'
    return render_template('trainer_dashboard.html',
        trainer=user, athletes=athletes,
        total_sessions=total_sessions, appointments=appts)

# ─── Doctor Dashboard ─────────────────────────────────────────────────────────
@app.route('/doctor/dashboard')
@login_required
@role_required(['doctor'])
def doctor_dashboard():
    uid  = session['user_id']
    user = get_col('users').find_one({'_id':oid(uid)})
    athletes = list(get_col('athletes').find({}))
    h_recs   = list(get_col('health_records').find({}))
    emerg    = list(get_col('emergencies').find({'status':'active'}))
    ath_map  = {sid(a['_id']): a for a in athletes}
    # Appointments for THIS doctor
    appts = list(get_col('appointments').find({'doctor_id':uid}))
    for a in appts:
        ath = get_col('athletes').find_one({'_id':a.get('athlete_id')})
        a['athlete_name'] = ath.get('name','?') if ath else '?'
    return render_template('doctor_dashboard.html',
        doctor=user, athletes=athletes, health_records=h_recs[:20],
        emergencies=emerg, appointments=appts, ath_map=ath_map)

# ─── Admin Dashboard ──────────────────────────────────────────────────────────
@app.route('/admin/dashboard')
@login_required
@role_required(['admin'])
def admin_dashboard():
    uid  = session['user_id']
    user = get_col('users').find_one({'_id':oid(uid)})
    athletes    = list(get_col('athletes').find({}))
    tournaments = list(get_col('tournaments').find({}))
    return render_template('admin_dashboard.html',
        admin=user, athletes=athletes, tournaments=tournaments,
        verified_count=sum(1 for a in athletes if a.get('verified')),
        pending_count=sum(1 for a in athletes if not a.get('verified')),
        users_count=len(athletes), admin_region=user.get('region',''))

@app.route('/admin/statistics')
@login_required
@role_required(['admin'])
def admin_statistics():
    uid  = session['user_id']
    user = get_col('users').find_one({'_id':oid(uid)})
    athletes = list(get_col('athletes').find({}))
    details  = []
    for a in athletes:
        aid = a['_id']
        details.append({'athlete':a,
            'training_sessions': get_col('training_logs').count_documents({'athlete_id':aid}),
            'health_records':    get_col('health_records').count_documents({'athlete_id':aid}),
            'diet_logs':         get_col('diet_logs').count_documents({'athlete_id':aid}),
            'sport_score':       round(a.get('sport_score',0),2)})
    sb = {}
    for a in athletes:
        sp = a.get('sport','Unspecified') or 'Unspecified'
        sb[sp] = sb.get(sp,0)+1
    t = len(athletes)
    return render_template('admin_statistics.html',
        admin=user, athletes=details, total_athletes=t,
        verified_athletes=sum(1 for a in athletes if a.get('verified')),
        pending_athletes=sum(1 for a in athletes if not a.get('verified')),
        sports_breakdown=sb,
        avg_sport_score=round(sum(a.get('sport_score',0) for a in athletes)/t,2) if t else 0,
        total_training_logs=get_col('training_logs').count_documents({}),
        total_health_records=get_col('health_records').count_documents({}),
        total_diet_logs=get_col('diet_logs').count_documents({}))

# ─── Admin Actions ────────────────────────────────────────────────────────────
@app.route('/admin/athletes/<athlete_id>/verify', methods=['POST'])
@login_required
@role_required(['admin'])
def admin_verify_athlete(athlete_id):
    action   = request.form.get('action','verify')
    verified = (action == 'verify')
    get_col('athletes').update_one({'_id':oid(athlete_id)},
        {'$set':{'verified':verified,'verified_by':session['user_id'],'verified_at':datetime.now().isoformat()}})
    flash(f'Athlete {"verified" if verified else "unverified"} successfully.','success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/athletes/create', methods=['POST'])
@login_required
@role_required(['admin'])
def admin_create_athlete():
    data  = request.form
    email = data.get('email','').strip()
    if not email:
        flash('Email is required.','danger')
        return redirect(url_for('admin_dashboard'))
    if get_col('users').find_one({'email':email}):
        flash('Email already registered.','danger')
        return redirect(url_for('admin_dashboard'))
    res = get_col('users').insert_one({
        'email':email,'password':hash_password(data.get('password','default123')),
        'full_name':data.get('full_name',''),'role':'athlete',
        'region':data.get('region',''),'created_by_admin':session['user_id'],
        'created_at':datetime.now().isoformat()
    })
    get_col('athletes').insert_one({
        'user_id':res.inserted_id,'name':data.get('full_name',''),'email':email,
        'age':int(data.get('age',0) or 0),'gender':data.get('gender',''),
        'sport':data.get('sport',''),'region':data.get('region',''),
        'bio':data.get('bio',''),'achievements':[],'profile_photo':'',
        'visibility':data.get('visibility','trainer'),'sport_score':0,
        'verified':True,'managed_by_admin':session['user_id'],
        'created_at':datetime.now().isoformat()
    })
    flash(f'Athlete {data.get("full_name","")} created!','success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/athletes/<athlete_id>/update', methods=['POST'])
@login_required
@role_required(['admin'])
def admin_update_athlete(athlete_id):
    data = request.form
    get_col('athletes').update_one({'_id':oid(athlete_id)},
        {'$set':{'name':data.get('name'),'age':int(data.get('age',0) or 0),
                 'sport':data.get('sport'),'region':data.get('region'),
                 'bio':data.get('bio',''),'updated_at':datetime.now().isoformat()}})
    flash('Athlete updated!','success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/tournament/create', methods=['POST'])
@login_required
@role_required(['admin','trainer'])
def admin_create_tournament():
    data = request.form
    if not all([data.get('name'),data.get('sport'),data.get('location'),data.get('start_date'),data.get('end_date')]):
        flash('All tournament fields are required.','danger')
        return redirect(url_for('admin_dashboard'))
    get_col('tournaments').insert_one({
        'name':data.get('name'),'sport':data.get('sport'),'location':data.get('location'),
        'start_date':data.get('start_date'),'end_date':data.get('end_date'),
        'description':data.get('description',''),'participants':[],
        'created_by':session['user_id'],'created_at':datetime.now().isoformat()
    })
    flash('Tournament created!','success')
    return redirect(url_for('admin_dashboard'))

# ─── Trainer Tournament Create ────────────────────────────────────────────────
@app.route('/trainer/tournament/create', methods=['POST'])
@login_required
@role_required(['trainer','admin'])
def trainer_create_tournament():
    data = request.form
    if not all([data.get('name'),data.get('sport'),data.get('location'),data.get('start_date'),data.get('end_date')]):
        flash('All fields required.','danger')
        return redirect(url_for('trainer_dashboard'))
    get_col('tournaments').insert_one({
        'name':data.get('name'),'sport':data.get('sport'),'location':data.get('location'),
        'start_date':data.get('start_date'),'end_date':data.get('end_date'),
        'description':data.get('description',''),'participants':[],
        'created_by':session['user_id'],'created_at':datetime.now().isoformat()
    })
    flash('Tournament created!','success')
    return redirect(url_for('trainer_dashboard'))

# ─── Athlete Profile ──────────────────────────────────────────────────────────
@app.route('/athlete/profile')
@login_required
def athlete_profile():
    athlete = get_col('athletes').find_one({'user_id':oid(session['user_id'])}) or {}
    return render_template('athlete_profile.html', athlete=athlete)

@app.route('/athlete/profile/update', methods=['POST'])
@login_required
def update_athlete_profile():
    data = request.form
    get_col('athletes').update_one({'user_id':oid(session['user_id'])},
        {'$set':{'name':data.get('name'),'age':int(data.get('age',0) or 0),
                 'gender':data.get('gender'),'sport':data.get('sport'),
                 'region':data.get('region'),'bio':data.get('bio'),
                 'visibility':data.get('visibility','private'),'updated_at':datetime.now().isoformat()}})
    flash('Profile updated!','success')
    return redirect(url_for('athlete_dashboard'))

@app.route('/athlete/<athlete_id>')
def public_athlete_profile(athlete_id):
    try:
        athlete = get_col('athletes').find_one({'_id':oid(athlete_id)})
        if not athlete: return render_template('athlete_profile.html', error='Athlete not found')
        if athlete.get('visibility') == 'private': return render_template('athlete_profile.html', error='Profile is private')
        aid  = athlete['_id']
        t    = sorted(list(get_col('training_logs').find({'athlete_id':aid})),key=lambda x:x.get('date',''),reverse=True)
        h    = sorted(list(get_col('health_records').find({'athlete_id':aid})),key=lambda x:x.get('date',''),reverse=True)
        d    = list(get_col('diet_logs').find({'athlete_id':aid}))
        return render_template('athlete_profile.html',
            athlete=athlete, sport_score=calculate_sport_score(aid),
            performance=analyze_performance(aid),
            training_logs=t[:10], health_records=h[:12], diet_logs=d[:30], public=True)
    except Exception as e:
        print(f'public_profile err: {e}')
        return render_template('athlete_profile.html', error='Invalid athlete ID')

@app.route('/athlete/id-card')
@login_required
def athlete_id_card():
    athlete = get_col('athletes').find_one({'user_id':oid(session['user_id'])})
    if not athlete: return redirect(url_for('athlete_profile'))
    qr_url  = request.host_url.rstrip('/') + url_for('public_athlete_profile',athlete_id=sid(athlete['_id']))
    return render_template('id_card.html', athlete=athlete, qr_code=generate_qr_code(qr_url), qr_data=qr_url)

# ─── Logging Routes ───────────────────────────────────────────────────────────
@app.route('/athlete/training/log', methods=['GET','POST'])
@login_required
def log_training():
    athlete = get_col('athletes').find_one({'user_id':oid(session['user_id'])})
    if not athlete: return redirect(url_for('athlete_profile'))
    if request.method == 'POST':
        data = request.form
        get_col('training_logs').insert_one({'athlete_id':athlete['_id'],'user_id':oid(session['user_id']),
            'date':data.get('date'),'workout_type':data.get('workout_type'),
            'duration':int(data.get('duration',0) or 0),'intensity':int(data.get('intensity',50) or 50),
            'notes':data.get('notes',''),'created_at':datetime.now().isoformat()})
        flash('Training session logged!','success')
        return redirect(url_for('athlete_dashboard'))
    return render_template('training_log.html', athlete=athlete)

@app.route('/athlete/health/log', methods=['GET','POST'])
@login_required
def log_health():
    athlete = get_col('athletes').find_one({'user_id':oid(session['user_id'])})
    if not athlete: return redirect(url_for('athlete_profile'))
    if request.method == 'POST':
        data = request.form
        h = float(data.get('height',170) or 170); w = float(data.get('weight',65) or 65)
        get_col('health_records').insert_one({'athlete_id':athlete['_id'],'user_id':oid(session['user_id']),
            'date':data.get('date'),'height':h,'weight':w,'bmi':round(w/(h/100)**2,1),
            'heart_rate':int(data.get('heart_rate',0) or 0),'blood_pressure':data.get('blood_pressure',''),
            'sleep_hours':float(data.get('sleep_hours',7) or 7),'injury_notes':data.get('injury_notes',''),
            'created_at':datetime.now().isoformat()})
        flash('Health record saved!','success')
        return redirect(url_for('athlete_dashboard'))
    return render_template('health_log.html', athlete=athlete)

@app.route('/athlete/diet/log', methods=['GET','POST'])
@login_required
def log_diet():
    athlete = get_col('athletes').find_one({'user_id':oid(session['user_id'])})
    if not athlete: return redirect(url_for('athlete_profile'))
    if request.method == 'POST':
        data = request.form
        get_col('diet_logs').insert_one({'athlete_id':athlete['_id'],'user_id':oid(session['user_id']),
            'date':data.get('date'),'meal':data.get('meal',''),
            'calories':int(data.get('calories',0) or 0),'protein':int(data.get('protein',0) or 0),
            'carbs':int(data.get('carbs',0) or 0),'fats':int(data.get('fats',0) or 0),
            'water_intake':int(data.get('water_intake',0) or 0),'notes':data.get('notes',''),
            'created_at':datetime.now().isoformat()})
        flash('Diet logged!','success')
        return redirect(url_for('athlete_dashboard'))
    return render_template('diet_log.html', athlete=athlete)

# ─── Tournaments ──────────────────────────────────────────────────────────────
@app.route('/tournaments')
@login_required
def tournaments():
    sf = request.args.get('sport','').lower()
    all_t = list(get_col('tournaments').find({}))
    if sf: all_t = [t for t in all_t if sf in (t.get('sport') or '').lower()]
    return render_template('tournament_finder.html', tournaments=all_t, sport_filter=sf)

# ─── Appointments ─────────────────────────────────────────────────────────────
@app.route('/appointments', methods=['GET','POST'])
@login_required
def appointments():
    uid  = session['user_id']
    user = get_col('users').find_one({'_id':oid(uid)})
    role = user.get('role','athlete') if user else 'athlete'

    if request.method == 'POST':
        data  = request.form
        atype = data.get('type','')
        tr_id = data.get('trainer_id','').strip()
        dr_id = data.get('doctor_id','').strip()

        # Resolve athlete _id
        if role == 'athlete':
            ath = get_col('athletes').find_one({'user_id':oid(uid)})
            ath_id = ath['_id'] if ath else oid(uid)
        else:
            ath_id = oid(data.get('athlete_id', uid))

        doc = {'athlete_id':ath_id,'type':atype,
               'appointment_date':data.get('appointment_date',''),
               'time':data.get('time',''),'notes':data.get('notes',''),
               'status':'pending','created_at':datetime.now().isoformat()}
        # Store as string IDs so query `{'trainer_id': uid}` works
        if tr_id: doc['trainer_id'] = tr_id
        if dr_id: doc['doctor_id']  = dr_id

        get_col('appointments').insert_one(doc)
        flash('Appointment booked!','success')
        return redirect(url_for('appointments'))

    # GET
    if role == 'athlete':
        ath = get_col('athletes').find_one({'user_id':oid(uid)})
        appts = list(get_col('appointments').find({'athlete_id':ath['_id']})) if ath else []
    elif role == 'doctor':
        appts = list(get_col('appointments').find({'doctor_id':uid}))
    elif role == 'trainer':
        appts = list(get_col('appointments').find({'trainer_id':uid}))
    else:
        appts = list(get_col('appointments').find({}))

    for a in appts:
        ath = get_col('athletes').find_one({'_id':a.get('athlete_id')})
        a['athlete_name'] = ath.get('name','Unknown') if ath else 'Unknown'
        # Lookup professional names
        if a.get('trainer_id'):
            tr = get_col('users').find_one({'_id':oid(a['trainer_id'])})
            a['trainer_name'] = tr.get('full_name','') if tr else ''
        if a.get('doctor_id'):
            dr = get_col('users').find_one({'_id':oid(a['doctor_id'])})
            a['doctor_name'] = dr.get('full_name','') if dr else ''

    trainers = list(get_col('users').find({'role':'trainer'}))
    doctors  = list(get_col('users').find({'role':'doctor'}))

    return render_template('appointments.html',
        appointments=appts, trainers=trainers, doctors=doctors, user_role=role)

# ─── Chatbot ──────────────────────────────────────────────────────────────────
@app.route('/athlete/chatbot', methods=['GET','POST'])
@login_required
def chatbot():
    athlete = get_col('athletes').find_one({'user_id':oid(session['user_id'])})
    if not athlete: return redirect(url_for('athlete_profile'))
    if request.method == 'POST':
        q = (request.json or {}).get('question','').strip()
        if not q: return jsonify({'error':'No question'})
        resp = ai_chatbot_response(q)
        get_col('ai_chats').insert_one({'athlete_id':athlete['_id'],'question':q,'response':resp,'created_at':datetime.now().isoformat()})
        return jsonify({'response':resp,'bot':'SportEquity AI'})
    chats = sorted(list(get_col('ai_chats').find({'athlete_id':athlete['_id']})),key=lambda x:x.get('created_at',''),reverse=True)
    return render_template('chatbot.html', athlete=athlete, chat_history=chats[:20])

# ─── Emergency ────────────────────────────────────────────────────────────────
@app.route('/athlete/emergency', methods=['POST'])
@login_required
def trigger_emergency():
    athlete = get_col('athletes').find_one({'user_id':oid(session['user_id'])})
    if not athlete: return jsonify({'status':'error'})
    get_col('emergencies').insert_one({
        'athlete_id':athlete['_id'],'athlete_name':athlete.get('name','?'),
        'triggered_at':datetime.now().isoformat(),'status':'active'})
    return jsonify({'status':'emergency_triggered','message':'Emergency alert sent! Help is on the way.'})

# ─── Analytics API ────────────────────────────────────────────────────────────
@app.route('/api/athlete/<athlete_id>/analytics')
def get_athlete_analytics(athlete_id):
    try:
        aid  = oid(athlete_id)
        t    = sorted(list(get_col('training_logs').find({'athlete_id':aid})),key=lambda x:x.get('date',''))[-7:]
        h    = sorted(list(get_col('health_records').find({'athlete_id':aid})),key=lambda x:x.get('date',''))[-12:]
        d    = sorted(list(get_col('diet_logs').find({'athlete_id':aid})),key=lambda x:x.get('date',''))[-7:]
        return jsonify({
            'training':{'dates':[l.get('date','')[:10] for l in t],'intensities':[int(l.get('intensity',0)) for l in t],'durations':[int(l.get('duration',0)) for l in t]},
            'health':  {'dates':[l.get('date','')[:10] for l in h],'heart_rates':[int(l.get('heart_rate',0)) for l in h],'weights':[float(l.get('weight',0)) for l in h],'bmis':[float(l.get('bmi',0)) for l in h]},
            'diet':    {'dates':[l.get('date','')[:10] for l in d],'calories':[int(l.get('calories',0)) for l in d],'proteins':[int(l.get('protein',0)) for l in d]}
        })
    except Exception as e: return jsonify({'error':str(e)}), 400

@app.route('/api/athlete/<athlete_id>/diet-analysis')
def diet_analysis_api(athlete_id):
    try:
        d = list(get_col('diet_logs').find({'athlete_id':oid(athlete_id)}))
        return jsonify(analyze_diet(d))
    except Exception as e: return jsonify({'error':str(e)})

# ─── Seed Demo ────────────────────────────────────────────────────────────────
@app.route('/seed-demo-data')
def seed_demo_data():
    for col in ['users','athletes','training_logs','health_records','diet_logs','tournaments']:
        get_col(col).delete_many({})
    demo = [
        {'email':'athlete@sportequity.com','full_name':'Priya Sharma','role':'athlete','region':'Mumbai','specialization':''},
        {'email':'trainer@sportequity.com','full_name':'Rahul Trainer','role':'trainer','region':'Mumbai','specialization':'Sprinting & Strength'},
        {'email':'doctor@sportequity.com', 'full_name':'Dr. Anjali Singh','role':'doctor','region':'Mumbai','specialization':'Sports Medicine'},
        {'email':'admin@sportequity.com',  'full_name':'Community Admin','role':'admin','region':'Mumbai','specialization':''},
    ]
    for d in demo: d['password']=hash_password('password123'); d['created_at']=datetime.now().isoformat()
    u_res = get_col('users').insert_many(demo)
    a_uid, tr_uid, dr_uid = u_res.inserted_ids[0], u_res.inserted_ids[1], u_res.inserted_ids[2]
    ar = get_col('athletes').insert_one({'user_id':a_uid,'name':'Priya Sharma','email':'athlete@sportequity.com',
        'age':22,'gender':'Female','sport':'Athletics','region':'Mumbai',
        'bio':'Aspiring sprinter from rural Maharashtra','achievements':['State Bronze 200m 2023','District Champion 2022'],
        'profile_photo':'','visibility':'public','sport_score':0,'verified':True,'created_at':datetime.now().isoformat()})
    aid = ar.inserted_id
    for i in range(15):
        d = (datetime.now()-timedelta(days=15-i)).strftime('%Y-%m-%d')
        get_col('training_logs').insert_one({'athlete_id':aid,'user_id':a_uid,'date':d,
            'workout_type':'Cardio' if i%2==0 else 'Strength','duration':45+(i%30),'intensity':50+(i%35),
            'notes':f'Session {i+1}','created_at':datetime.now().isoformat()})
    for i in range(8):
        d = (datetime.now()-timedelta(days=30-i*4)).strftime('%Y-%m-%d')
        h,w = 162,55+(i%4)
        get_col('health_records').insert_one({'athlete_id':aid,'user_id':a_uid,'date':d,'height':h,'weight':w,
            'bmi':round(w/(h/100)**2,1),'heart_rate':62+(i%8),'blood_pressure':'116/74',
            'sleep_hours':7+(i%2),'injury_notes':'','created_at':datetime.now().isoformat()})
    for i in range(14):
        d = (datetime.now()-timedelta(days=14-i)).strftime('%Y-%m-%d')
        get_col('diet_logs').insert_one({'athlete_id':aid,'user_id':a_uid,'date':d,'meal':f'Day {i+1} meals',
            'calories':2000+(i%300),'protein':65+(i%25),'carbs':240+(i%60),'fats':55+(i%20),
            'water_intake':2500+(i%500),'notes':'','created_at':datetime.now().isoformat()})
    get_col('tournaments').insert_many([
        {'name':'Mumbai Regional Athletics','sport':'Athletics','location':'Mumbai',
         'start_date':(datetime.now()+timedelta(days=30)).strftime('%Y-%m-%d'),
         'end_date':(datetime.now()+timedelta(days=32)).strftime('%Y-%m-%d'),
         'description':'Annual district track meet. Open to all.','participants':[],'created_by':sid(tr_uid),'created_at':datetime.now().isoformat()},
        {'name':'Maharashtra Football Cup','sport':'Football','location':'Pune',
         'start_date':(datetime.now()+timedelta(days=60)).strftime('%Y-%m-%d'),
         'end_date':(datetime.now()+timedelta(days=65)).strftime('%Y-%m-%d'),
         'description':'State-level football tournament U25.','participants':[],'created_by':sid(tr_uid),'created_at':datetime.now().isoformat()},
    ])
    return jsonify({'status':'success','message':'Demo data loaded!',
        'accounts':{'athlete':'athlete@sportequity.com / password123','trainer':'trainer@sportequity.com / password123',
                    'doctor':'doctor@sportequity.com / password123','admin':'admin@sportequity.com / password123'}})

@app.context_processor
def inject_globals():
    """Make 'now' (today's date string) available in every template."""
    return {'now': datetime.now().strftime('%Y-%m-%d')}

@app.errorhandler(404)
def not_found(e): return render_template('404.html'), 404

@app.errorhandler(500)
def server_error(e): return render_template('500.html'), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
