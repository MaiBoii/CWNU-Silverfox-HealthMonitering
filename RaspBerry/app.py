"""
구현해야하는 기능들 
1. 시리얼 통신으로 받은 TodayWeight, workout_time, distance,Heartbeat,Oxygen,Temperature 데이터를 데이터베이스에 저장
2. 시리얼 통신으로 받은 위치정보 실시간으로 (3분 간격) 전역변수 LOCATION에 저장
3. 긴급 상황시 보호자 스마트폰으로 가장 최근의 위치정보 송신
4. 시리얼 통신으로 받은 데이터가 'Weight'일 경우, 오늘치 데이터가 없으면 데이터 입력, 있으면 평균내서 데이터 수정
5. 시리얼 통신으로 받은 데이터가 'Distance'일 경우, 오늘치 데이터가 없으면 데이터 입력, 있으면 더해서 데이터 수정
6. 시리얼 통신으로 받은 데이터가 'Emergency'일 경우, 긴급 상황이라는 메시지를 보호자 스마트폰으로 전송
7. 시리얼 통신으로 받은 데이터가 'Location'일 경우, 위치 정보를 갱신 
8. 시리얼 통신으로 받은 데이터가 'Heartbeat'일 경우, 오늘치 데이터가 없으면 데이터 입력, 있으면 평균내서 데이터 수정
9. 시리얼 통신으로 받은 데이터가 'Oxygen'일 경우, 오늘치 데이터가 없으면 데이터 입력, 있으면 평균내서 데이터 수정
10. 시리얼 통신으로 받은 데이터가 'Temperature'일 경우, 오늘치 데이터가 없으면 데이터 입력, 있으면 평균내서 데이터 수정
"""

from flask import Flask, render_template,request,jsonify
from models import db,Profile,Workout,Year,month_avg,avg,Token
#from utils import create_dummy_data
import serial
import os
import json
from dotenv import load_dotenv
from sqlalchemy import extract, func,desc
from datetime import datetime, timedelta
from sqlalchemy.exc import IntegrityError
import threading
import schedule
import time

import firebase_admin
from firebase_admin import credentials
from firebase_admin import messaging


# .env 파일로부터 환경 변수 로드
load_dotenv()

# 데이터베이스 관련 환경 변수 로드
db_host = os.getenv("DB_URI")

# 시리얼 통신 관련 환경 변수 로드
ser_port = os.getenv("SER_PORT")
ser_baud = os.getenv("SER_BAUD")

# 시리얼 통신 객체 생성
ser = serial.Serial(ser_port, ser_baud)

# Flask 앱 생성
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = db_host # MySQL 연결 정보 입력
db.init_app(app)

# 데이터베이스 생성
with app.app_context():
    db.create_all()
    #create_dummy_data()

# 시리얼 통신으로부터 받은 데이터를 저장할 전역 변수 선언

SERIAL_DATA = {
    "Oxygen": 0,
    "Distance": 0,
    "WorkoutTime": {"hours": 0, "minutes": 0},
    "Temperature": 0,
    "Heartbeat": 0,
    "Weight": 0
}

LOCATION = {
      "latitude": 0,
      "longitude": 0
}


# ------------------------------  FireBase FCM 관련 모음  --------------------------------------------

# Firebase Admin SDK 초기화 (최초에만 호출)
if not firebase_admin._apps:
    cred_path = os.path.join(os.environ['HOME'], "rasp/RaspBerry/healthcare-28246-firebase-adminsdk-dwe3z-591680be1e.json")
    cred = credentials.Certificate(cred_path)
    firebase_admin.initialize_app(cred)

# 앱으로부터 토큰 수신 후 DB 저장
@app.route('/token', methods=['POST'])
def save_user_profile():
    get_token = request.json 
    token = get_token.get('token')

    # 데이터베이스에서 토큰 확인
    existing_token = Token.query.filter_by(token=token).first()
    
    if existing_token is None:
        # 토큰이 데이터베이스에 없으면 저장
        new_token = Token(token=token)
        db.session.add(new_token)
        db.session.commit()
        print("새로운 FCM 토큰이 저장되었습니다.")
        return 200
    else:
        # 있으면 그냥 pass
        return 200

# 요청시 위도경도 전송하기
@app.route('/location', methods=['GET'])
def send_location():
    data = {
        'latitude': LOCATION['latitude'],
        'longitude': LOCATION['longitude']
    }
    return jsonify(data), 200

# 안전사고시 fcm 메시지 전송
def send_fcm_notification(token):
    message = messaging.Message(
        notification=messaging.Notification(
            title="안전사고 발생!",
            body= "안전사고가 발생했습니다. 위치를 확인해주세요."
        ),
        data={
            # 위도 경도 넣기
         'latitude': LOCATION['latitude'],
         'longitude': LOCATION['longitude']
        }
    )
    response = messaging.send(message)

# ---------------------------------------------------------------------------------------------

# ------------------------------  Serial 관련 스레드 모음  --------------------------------------------

# SERIAL_DATA의 내부 데이터 출력 함수
def print_serial_data():
    print("Oxygen:", SERIAL_DATA["Oxygen"])
    print("Distance:", SERIAL_DATA["Distance"])
    print("WorkoutTime:", SERIAL_DATA["WorkoutTime"])
    print("Temperature:", SERIAL_DATA["Temperature"])
    print("Heartbeat:", SERIAL_DATA["Heartbeat"])
    print("Weight:", SERIAL_DATA["Weight"])
    print()

# LOCATION의 내부 데이터 출력 함수
def print_location_data():
    print("LOCATION:")
    for key, value in LOCATION.items():
        print(f"{key}: {value}")
    print()

# 데이터베이스에 운동 데이터 저장
def save_workout_data():
    new_workout = Workout(
        date=datetime.now().date(),
        distance=SERIAL_DATA["Distance"],
        workout_time=datetime.strptime(f"{SERIAL_DATA['WorkoutTime']['hours']}:{SERIAL_DATA['WorkoutTime']['minutes']}", "%H:%M").time(),
        today_weight=SERIAL_DATA["Weight"],
        oxygen=SERIAL_DATA["Oxygen"],
        temp=SERIAL_DATA["Temperature"],
        heart=SERIAL_DATA["Heartbeat"]
    )
    db.session.add(new_workout)

    try:
        db.session.commit()
        print("Workout 데이터가 성공적으로 저장되었습니다.")
    except IntegrityError as e:
        db.session.rollback()
        print("에러가 발생하였습니다.:", e)

# 시리얼 통신 함수
def serial_thread():
   while True:
        # 시리얼 데이터 읽기
        serial_data = ser.readline().decode('utf-8').strip()
        
        # 데이터 확인 및 처리
        if serial_data.startswith("{") and serial_data.endswith("}"):
            # 시리얼 데이터가 JSON 형식인 경우에만 처리
            try:
                # JSON 형식의 데이터를 딕셔너리로 변환
                data_dict = json.loads(serial_data)
                
                # 각 항목을 해당 변수에 업데이트
                for key, value in data_dict.items():
                    if key in SERIAL_DATA:
                        SERIAL_DATA[key] = value
                    elif key in LOCATION:
                        LOCATION[key] = value
                    else:
                        print("Unknown key:", key)

                # SERIAL_DATA와 LOCATION의 내부 데이터가 전부 갱신될 때 출력
                if all(SERIAL_DATA.values()) or all(LOCATION.values()):
                    print_serial_data()
                    print_location_data()

            except ValueError:
                print("Invalid JSON format:", serial_data)
                continue

# ---------------------------------------------------------------------------------------------


# ------------------------------  Flask 스레드 관련 함수 모음  --------------------------------------------

# 메인 페이지
@app.route('/')
def index():
    return render_template('index.html')

#가장 최근 토큰 가져오기
def get_latest_token():
    latest_token = Token.query.order_by(Token.id.desc()).first()
    if latest_token:
        return latest_token.token
    else:
        return None

#긴급상황 발생시 fcm 메시지 전송
@app.route('/emergency', methods=['GET'])
def emergency():
    latest_token = get_latest_token()
    if latest_token:
        send_fcm_notification(latest_token)
        return '', 200
    else:
        return 'No token found', 404

#개인정보 GET 전송
@app.route('/profile', methods=['POST'])
def db_profile():
  if request.method == 'POST':
    user_info = request.json
    name = user_info.get('name')
    age = user_info.get('age')
    height = user_info.get('height')
    init_weight = user_info.get('init_weight')
    new_profile = Profile(
                     name=name, 
                     age=age, 
                     height=height, 
                     init_weight=init_weight
                  )
    db.session.add(new_profile)
    db.session.commit()
    return jsonify(user_info), 200


#운동정보 GET 전송
@app.route('/workout', methods=['GET', 'POST'])
def db_workout():
   if request.method == 'GET':
      workouts = Workout.query.all()
      data_work = [{'workout_id':work.workout_id,'time':work.date.strftime("%Y-%m-%d %H:%M:%S"), 'distance':work.distance, 'workout_time':work.workout_time.strftime("%H:%M:%S"), 'today_weight':work.today_weight, 'oxygen':work.oxygen, 'temp':work.temp, 'heart':work.heart} for work in workouts]
      return jsonify({'workout_info':data_work})

   #운동정보 POST 저장
   elif request.method == 'POST':
                data_work = request.get_json()
                date = data_work['date']
                distance = data_work['distance']
                workout_time = data_work['workout_time']
                today_weight = data_work['today_weight']
                oxygen = data_work['oxygen']
                temp = data_work['temp']
                heart = data_work['heart']
                new_workout = Workout(date=date, distance=distance, workout_time=workout_time, today_weight=today_weight, oxygen=oxygen, temp=temp, heart=heart)

                db.session.add(new_workout)
                db.session.commit()
                return jsonify({'message':'workout added successfully'})
 
#12개월 평균 계산 함수
@app.route('/monthly_avg', methods=['GET'])
def monthly_average():
   latest_date = db.session.query(func.max(Workout.date)).scalar()
   second_latest_date = db.session.query(func.max(Workout.date)).filter(Workout.date < latest_date).scalar()

   latest_year, latest_month = latest_date.year, latest_date.month
   second_latest_year, second_latest_month = second_latest_date.year, second_latest_date.month
   if (latest_month != second_latest_month) or (latest_year != second_latest_year):
      monthly_average = (
         db.session.query(
            extract('year', Workout.date).label('year'),
            extract('month', Workout.date).label('month'),
            db.func.avg(func.nullif(func.time_to_sec(Workout.workout_time), 0)).label('avg_time'),
            db.func.avg(func.nullif(Workout.today_weight, 0)).label('avg_weight'),
            db.func.avg(func.nullif(Workout.distance, 0)).label('avg_distance'),
            db.func.avg(func.nullif(Workout.temp, 0)).label('avg_temp'),
            db.func.avg(func.nullif(Workout.oxygen, 0)).label('avg_oxygen'),
            db.func.avg(func.nullif(Workout.heart, 0)).label('avg_heart')
         )
         .filter(func.extract('year', Workout.date) == second_latest_year,
                    func.extract('month', Workout.date) == second_latest_month)
            .group_by(extract('year', Workout.date), extract('month', Workout.date))
            .all()
      )
      result = []
      for average in monthly_average:
         year_month = f"{average.year}-{average.month:02d}-01"
         avg_time_seconds = int(average.avg_time)
         avg_hours = int(avg_time_seconds // 3600)
         avg_minutes = int((avg_time_seconds % 3600) // 60)
         avg_seconds = int(avg_time_seconds % 60)
         avg_time_str = f"{avg_hours:02d}:{avg_minutes:02d}:{avg_seconds:02d}"
         existing_year_month = db.session.query(Year).filter_by(date=year_month).first()
         if not existing_year_month:
            result.append({
               'date':year_month,
               'avg_time':avg_time_str,
               'avg_weight':round(average.avg_weight, 2),
               'avg_distance':round(average.avg_distance, 2),
               'avg_temp':round(average.avg_temp, 2),
               'avg_oxygen':round(average.avg_oxygen, 2),
               'avg_heart':round(average.avg_heart, 2)
            })
            year_data = Year(
               date=year_month,
               workout_time=avg_time_str,
               today_weight = round(average.avg_weight, 2),
               distance = round(average.avg_distance, 2),
               temp=round(average.avg_temp, 2),
               oxygen=average.avg_oxygen,
               heart=average.avg_heart
            )
            try:
               db.session.add(year_data)
               db.session.commit()
            except IntegrityError:
               print("IntegrityError 발생:", e)
               db.session.rollback()
      db.session.commit()
      return jsonify(result)
   else:
      return jsonify({'message': '이전 달의 데이터가 없습니다.'})

#앱-메인페이지 전송 (가장 최근 심박, 체중, 체온, 시간, 거리, 산소 데이터)
@app.route('/main', methods=['GET'])
def main_info():
   #내림차순 정렬 후 가장 최근 데이터를 가져옴
   workout_data = Workout.query.order_by(desc(Workout.date)).first()
   profile_data = Profile.query.first()
   time_str = workout_data.workout_time.strftime('%H:%M')

   data = {'last_workout_data':{
                  'name': profile_data.name, 
                  'date':workout_data.date.strftime('%Y-%m-%d'), 
                  'distance':workout_data.distance, 
                  'workout_time':workout_data.workout_time.strftime('%H:%M'), 
                  'today_weight':workout_data.today_weight, 
                  'oxygen':workout_data.oxygen, 
                  'temp':workout_data.temp, 
                  'heart':workout_data.heart}
               }
   return jsonify(data)

#앱-7일치 요구시 데이터 전송
@app.route('/days/<field>', methods=['GET'])
def days_data(field):
   week_data = Workout.query.order_by(desc(Workout.date)).first()
   oneWeek_data = week_data.date - timedelta(days=7)
   OneWeek_data = Workout.query.filter(Workout.date > oneWeek_data).all()
   data = {'7days_data':[]}
   for data_days in OneWeek_data:
      if field == 'workout_time':
         time_str = data_days.workout_time.strftime("%H:%M")
         data['7days_data'].append({'date':data_days.date.strftime("%Y-%m-%d"), 'workout_time':time_str})
      else:
         data['7days_data'].append({'date':data_days.date.strftime("%Y-%m-%d"), field:getattr(data_days, field)})
   return jsonify(data)

#앱-31일치 요구시 데이터 전송
@app.route('/months/<field>', methods=['GET'])
def data_months(field):
   latest_workout_data = Workout.query.order_by(desc(Workout.date)).first()
   one_month_ago = latest_workout_data.date - timedelta(days=31)
   workout_data_in_last_month = Workout.query.filter(Workout.date > one_month_ago).all()
   data = {'31days_data':[]}
   for workout_data in workout_data_in_last_month:
      if field == 'workout_time':
         time_str = workout_data.workout_time.strftime("%H:%M")
         data['31days_data'].append({'date':workout_data.date.strftime("%Y-%m-%d"), 'workout_time':time_str})
      else:
         data['31days_data'].append({'date':workout_data.date.strftime("%Y-%m-%d"), field:getattr(workout_data, field)})
   return jsonify(data)

#앱-연간 데이터 요구시 데이터 전송
@app.route('/years/<field>', methods=['GET'])
def year(field):
   year_data = Year.query.all()
   data = {'12months_data' : []}
   for i in year_data:
      if field == 'workout_time':
         time_str = i.workout_time.strftime("%H:%M")
         data['12months_data'].append({'date': i.date.strftime("%Y-%m"), 'workout_time': time_str})
      else:
         data['12months_data'].append({'date': i.date.strftime("%Y-%m"), field:getattr(i, field)})
   return jsonify(data)

# ---------------------------------------------------------------------------------------------

if __name__ == '__main__':
      
      # 시리얼 통신 스레드 시작
      serial_thread = threading.Thread(target=serial_thread)
      serial_thread.daemon = True
      serial_thread.start()

      # 스케줄러 작업 등록: 매일 자정 1분 전에 save_workout_data 함수 호출
      schedule.every().day.at("23:59:00").do(save_workout_data)

      app.run('0.0.0.0', port=5000, debug=False, threaded =True)

      # 계속해서 스케줄러된 작업을 실행
      while True:
         schedule.run_pending()
         time.sleep(1)  # 1분마다 스케줄링된 작업을 확인합니다.