# Увеличение снимка ×4 сетью Real-ESRGAN из tools/uluchshit-video.py
import sys, importlib.util, numpy as np, subprocess
spec = importlib.util.spec_from_file_location('u', '/home/mokeeva/main/tools/uluchshit-video.py')
u = importlib.util.module_from_spec(spec); spec.loader.exec_module(u)
vhod, vyhod, shum = sys.argv[1], sys.argv[2], float(sys.argv[3])
w, h = map(int, subprocess.check_output(['ffprobe','-v','error','-select_streams','v','-show_entries','stream=width,height','-of','csv=p=0',vhod]).decode().split(','))
kadr = np.frombuffer(subprocess.check_output(['ffmpeg','-v','error','-i',vhod,'-f','rawvideo','-pix_fmt','rgb24','-']), np.uint8).reshape(h, w, 3)
itog = u.UluchshitKadr(u.ZagruzitModel(shum), kadr, plitka=256)
subprocess.run(['ffmpeg','-v','error','-y','-f','rawvideo','-pix_fmt','rgb24','-s',f'{w*4}x{h*4}','-i','-',vyhod], input=itog.tobytes(), check=True)
print(vyhod, itog.shape)
