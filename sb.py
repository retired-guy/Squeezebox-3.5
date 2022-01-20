#!/usr/bin/python3
from LMSTools import LMSServer, LMSPlayer, LMSTags as tags
from time import sleep
import requests
import textwrap
import re
#import numpy as np

from datetime import datetime
from evdev import InputDevice, categorize, ecodes
from threading import Thread

from PIL import Image
from PIL import ImageFont
from PIL import ImageDraw

############## CHANGE ME! ###################
SERVER = '192.168.68.121' # ip address of Logitech Media Server
PORT = '9000'
PLAYER = 'RME Coax'


###### I/O devices may be different on your setup #####
###### can optionally use numpy to write to fb ########
#h, w, c = 320, 480, 4
#fb = np.memmap('/dev/fb0', dtype='uint8',mode='w+',shape=(h,w,c))

fbw, fbh = 480, 320         # framebuffer dimensions
fb = open("/dev/fb0", "wb") # framebuffer device

###### Touchscreen input device ######
dev = InputDevice('/dev/input/event0')

#######################################################

fonts = []
fonts.append( ImageFont.truetype('/usr/share/fonts/truetype/oswald/Oswald-Bold.ttf', 24) )
fonts.append( ImageFont.truetype('/usr/share/fonts/truetype/oswald/Oswald-Light.ttf', 20) )
fonts.append( ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf', 30) )
fonts.append( ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf', 144) )

## Touchscreen event worker thread
def event_thread():
  for event in dev.read_loop():
    if event.type == ecodes.EV_KEY:
      absevent = categorize(event)
      if absevent.event.value == 0:
        handle_event(dev)


## Red and Blue color channels are reversed from normal RGB on pi framebuffer
def swap_redblue(img):
  "Swap red and blue channels in image"
  r, g, b, a = img.split()
  return Image.merge("RGBA", (b, g, r, a))

## Paint image to screen at position
def blit(img, pos):

  size = img.size
  w = size[0]
  h = size[1]
  x = pos[0]
  y = pos[1]

### to use numpy, uncomment...
#  n = np.array(img)
#  n[:,:,[0,1,2]] = n[:,:,[2,1,0]]
#  fb[y:y+h,x:x+w] = n
### ... and comment all below

  img = swap_redblue(img)
  try:
    fb.seek(4 * ((pos[1]) * fbw + pos[0]))
  except Exception as e:
    print("seek error: ", e)

  iby = img.tobytes()
  for i in range(h):
    try:
      fb.write(iby[4*i*w:4*(i+1)*w])
      fb.seek(4 * (fbw - w), 1)
    except Exception as e:
      break


## Display date and time when idle
def displaydatetime(force):

  if not force:
    sec = datetime.now().second
    if sec not in {0,15,30,45}:
      return 

  dt = datetime.today().strftime('%a, %d %B %Y')
  tm = datetime.today().strftime('%H:%M')

  img = Image.new('RGBA',(480, 320))
  draw = ImageDraw.Draw(img)
  
  draw.text((20,10), tm, (255,255,255),font=fonts[3])
  draw.text((65,200), dt, (255,255,255),font=fonts[2])

  blit(img,(0,0))


## Red song progress line
def displayprogress(seek, duration):

  if duration > 0:
    progress = seek / duration * 480
  else:
    progress = 0

  img = Image.new('RGBA', (480, 6))

  draw = ImageDraw.Draw(img)
  draw.line((0,0,progress,0),fill='red',width=6)

  blit(img,(0,44))

## Display artist, song title, album title
def displaymeta(data):

  img = Image.new('RGBA',size=(210,270),color=(0,0,0,255))

  tw1 = textwrap.TextWrapper(width=30)
  tw2 = textwrap.TextWrapper(width=30)
  s = "\n"

  try:
    artist = data['artist']
  except:
    artist = ""

  try:
    title = data['title']
  except:
    title = ""

  try:
    album = data['album']
  except:
    album = ""

  if album == "":
    try:
      album = data['remote_title']
    except:
      pass

  artist = s.join(tw2.wrap(artist)[:6])
  album = s.join(tw2.wrap(album)[:6])

  draw = ImageDraw.Draw(img)

  draw.text((10,0), artist, (191,245,245),font=fonts[1])
  draw.text((10,165), album, (255,255,255),font=fonts[1])

  blit(img,(270,50))

  img = Image.new('RGBA',size=(480,50),color=(0,0,0,255))
  draw = ImageDraw.Draw(img)
  draw.text((0,0),  title, (255,255,255),font=fonts[0])

  blit(img,(0,0))

## Get album cover and display
def getcoverart(url):

  try:
    img = Image.open(requests.get(url, stream=True).raw)
    img = img.resize((270,270))
    img = img.convert('RGBA')

    blit(img,(0,50))
  except Exception as e:
    print(e)
    pass

## Handle touchscreen events
def handle_event(dev):
  global player,loop,session

  x1 = dev.absinfo(ecodes.ABS_X).value
  y1 = dev.absinfo(ecodes.ABS_Y).value
  x=int((y1/3850)*480)
  y=int((x1/3850)*320)

  try:
    if x >= 286:
      player.next()
      print("next")
    elif x>143 and x <286:
      player.toggle()
      print("play/pause")
    else:
      player.prev()
      print("prev")
  except Exception as e:
    print(e)
    pass


nowplaying = ''
old_nowplaying = ''
cover_url = ''
old_url = ''
old_playing = False
seek = 0
duration = 0
progress = 0
playing = False

## Start event handler thread
t = Thread(target=event_thread)
t.start()

## Init the screen
displaydatetime(True)

## Init LMS server and player
server = LMSServer(SERVER)
players = server.get_players()
for p in players:
  if p.name == PLAYER:
    print(p)
    player = p
    break 

#player = LMSPlayer(PLAYER, server)

nowplaying = ''
old_playing = True
old_nowplaying = ''
cover_url = ''
detail = [] 

taglist = [tags.ARTIST, tags.COVERID, tags.DURATION, tags.COVERART, tags.ARTWORK_URL, tags.ALBUM, tags.REMOTE_TITLE, tags.ARTWORK_TRACK_ID]

## Main loop - wait for player events, handle them
while True:

      try:
        playing = (player.mode == "play")
      except:
        playing = False

      if playing:
        detail = player.playlist_get_current_detail(amount=1,taglist=taglist)[0]
        try:
          if 'artwork_url' in detail:
            artwork_url = detail['artwork_url']
            if not artwork_url.startswith('http'):
              if artwork_url.startswith('/'):
                artwork_url = artwork_url[1:]

              cover_url = 'http://{}:{}/{}'.format(SERVER,PORT,artwork_url)
            else:
              cover_url = artwork_url
          else:
            cover_url='http://{}:{}/music/{}/cover.jpg'.format(SERVER,PORT,detail['artwork_track_id'])
        except Exception as e:
          print(e)


        nowplaying = detail['title']
        try:
          seek = player.time_elapsed
        except Exception as e:
          seek = 0

        try:
          duration = player.track_duration
        except Exception as e:
          duration = 0

      if not playing:
        displaydatetime(False)
        old_playing = playing
        detail = []
      elif playing and seek > 3:
        try:
          displayprogress(seek,duration)
        except Exception as e:
          progress = 0

      if playing != old_playing:
        old_playing = playing
        if playing:
          displayprogress(seek,duration)
          getcoverart(cover_url)
          displaymeta(detail)
        else:
          displaydatetime(False)

      if nowplaying != old_nowplaying or cover_url != old_url:
        old_nowplaying = nowplaying
        old_url = cover_url
        if playing:
          getcoverart(cover_url)
          displaymeta(detail)
        else:
          displaydatetime(False)

      sleep(1)


