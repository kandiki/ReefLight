from flask import Flask, request, render_template
import json
import time
import datetime
import paho.mqtt.client as mqtt
import pylunar
import threading
import math

server = Flask(__name__)
settings_file = "settings.json"


# 
# save, load and print the settings
#

# prints the actual settings
def print_settings():
  print("settings")
  print(json.dumps(settings,indent=2, sort_keys=True))
  
# saves the json to file
def save_settings():
  print("save json file")
  with open(settings_file, "w") as f:
    json.dump(settings, f, sort_keys=True, indent=2)
  
# load json from file
def load_settings():
  print("load json file")
  global settings
  with open(settings_file) as f:
      settings = json.load(f)
  print_settings()
  
  
  
  
  
  
  
  
#
# webserver handling
#

# index -> manual configuration of the different channels
@server.route('/')
def serve_index_to_client():
  print("a")
  #return server.send_static_file('index.html')
  return render_template('index.html')
 
# schedule -> config of the lightschedule
@server.route('/schedule.html')
def serve_schedule_to_client():
  return render_template('schedule.html')
  


# serves the json file
@server.route("/settings.json")
def serve_settings_to_client():
  # update to get the current settings
  update()
  # adds the localtime
  settings["server_time"] = time.strftime("%H:%M:%S", time.localtime())
  return json.dumps(settings,indent=2, sort_keys=True)
  
# saves the changes from the webserver and applies them
@server.route('/save', methods=['GET', 'POST'])
def save():
  global settings
  settings = request.json
  save_settings()
  update_and_send()
  return ''
  
  
# static files
# css
@server.route("/style.css")
def serve_css_():
  return server.send_static_file('style.css') 
 
# js libraries
@server.route("/jquery-3.3.1.js")
def serve_jquery_to_client():
  return server.send_static_file('jquery-3.3.1.js') 
@server.route("/highcharts.js")
def serve_highcharts_to_client():
  return server.send_static_file('highcharts.js') 
@server.route("/highcharts-more.js")
def serve_highcharts_more_to_client():
  return server.send_static_file('highcharts-more.js') 
@server.route("/highcharts-draggable-points.js")
def serve_highcharts_draggable_points_to_client():
  return server.send_static_file('highcharts-draggable-points.js') 









#
# mqtt stuff
#
def on_connect(client, userdata, flags, rc):
  print("connected to mqtt broker with result code "+str(rc))
  
  
# repeatedTimer class for the update
class RepeatedTimer(object):
  def __init__(self, interval, function, *args, **kwargs):
    self._timer     = None
    self.interval   = interval
    self.function   = function
    self.args       = args
    self.kwargs     = kwargs
    self.is_running = False
    self.first_time = True

  def _run(self):
    self.is_running = False
    self.start()
    self.function(*self.args, **self.kwargs)

  def start(self):
    if self.first_time:
      self.first_time = False
      self.start()
      self.function(*self.args, **self.kwargs)
    else:
      if not self.is_running:
          self._timer = threading.Timer(self.interval, self._run)
          self._timer.start()
          self.is_running = True
  
  def stop(self):
    self._timer.cancel()
    self.is_running = False


# updates the pwm values and sends them via MQTT
def update():  
  # current time
  cur_datetime = datetime.datetime.now()
  cur_utc_tm_info = time.gmtime()
  print("update at %s"%datetime.datetime.now())
  
  
  # loop over all channels
  for c, channel in enumerate(settings['channels']):
    
    print("   channel %d, %s"%(c,channel["name"]))
    
    # no update of the percentage in manual mode
    if channel['manual']:
      print("    manual mode, no update")
      pwm = channel["pwm"]
    
    
    
    # normal channel (new percentage calculated via interpolation of the data_points)
    if not channel['manual'] and not channel['moonlight']:
      
    # normal channel
    # new percentage updated via linear interpolation of the data_points
      print("    regular channel")
            
      # first load percentage and time values into the lists datetime_list and percentage_list
      datetime_list, pwm_list = [],[]
      for i in channel["data_points"]:
        # list of datetime.datetime values
        datetime_list.append(datetime.datetime.combine(cur_datetime.date(),datetime.time(*map(int, i[0].split(':')))))
        # list of % values
        pwm_list.append(float(i[1]))
        
      # periodic boundary conditions, so one interpolate between the last time of the day and the first time of the next day
      datetime_list.append(datetime_list[0]+datetime.timedelta(days=1))
      pwm_list.append(pwm_list[0])
      datetime_list.insert(0,datetime_list[-2]-datetime.timedelta(days=1))
      pwm_list.insert(0,pwm_list[-2])

      # searches the two times the current time is inbetween and interpolates linear the pwm value
      for i in range(len(datetime_list)-1):
        if datetime_list[i] < cur_datetime < datetime_list[i+1]:
          pwm = pwm_list[i]
          pwm += (pwm_list[i+1]-pwm_list[i])*((cur_datetime-datetime_list[i])/(datetime_list[i+1]-datetime_list[i]))
               
       
       
                 
    # moonlight channel
    # calc current brightness of the moon
    # percentage is max_moonlight_percentage times moonlight_brightness in percent
    if not channel['manual'] and channel['moonlight']:
      print("    moonlight channel")
      # create moonlight object using the location
      moon =  pylunar.MoonInfo(latitude=tuple(settings['latitude']), longitude=tuple(settings['longitude']))
      # feed time (utc time required)
      moon.update((
        cur_utc_tm_info.tm_year,
        cur_utc_tm_info.tm_mon,
        cur_utc_tm_info.tm_mday,
        cur_utc_tm_info.tm_hour,
        cur_utc_tm_info.tm_min,
        cur_utc_tm_info.tm_sec
      ))
      # ratio of the illuminated part of the moon
      fractional_phase = moon.fractional_phase()
      print("    fractional phase: %.3f"%(fractional_phase))
      # hight of the moon at your location
      altitude = moon.altitude()
      print("    altitude: %.3f°"%(altitude))
      
      pwm = float(channel["max_moonlight_pwm"]) * fractional_phase * math.sin(altitude)
      # if moon is not visible -> percentage = 0
      if pwm < 0:
        pwm = 0
        
          
    # update percentage in the settings
    settings['channels'][c]['pwm'] = pwm
    print("    pwm: %.3f"%pwm)
    
  # calculate current power
  settings['power'] = 0
  for channel in settings['channels']:
    settings['power'] += channel['max_power']*channel['pwm']
  print('  power [watt]: %.2f'%settings['power'])
  print()
  

def send():
  print("send at %s"%datetime.datetime.now())
  time.sleep(0.1)
  for c, channel in enumerate(settings['channels']):
    msg = channel['mqtt_cmd']%(1023*channel['pwm'])
    
    print('  topic: %s, msg: %s'%(settings['mqtt_topic'],msg))
  
    mqtt_client.publish(topic=settings['mqtt_topic'],payload = msg, qos = settings['mqtt_qos'])
    time.sleep(0.1)
  print()

def update_and_send():
  update()
  send()
  
if __name__ == "__main__":
  #loads the settings
  load_settings()
  
  # connect to MQTT broker
  mqtt_client = mqtt.Client(settings['mqtt_client_name'])
  mqtt_client.on_connect = on_connect
  mqtt_client.connect(host=settings['mqtt_broker'], port=int(settings['mqtt_port']))
  threading.Thread(target=mqtt_client.loop_forever).start()

  # start update timer
  timer = RepeatedTimer(10, update_and_send)
  timer.start()
  
  # start webserver in new thread (accessable from whole network at default port 5000
  threading.Thread(target=server.run, kwargs={'host':'0.0.0.0'}).start()

