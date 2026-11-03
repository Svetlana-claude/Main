"""Стенд для ~/tools/beget/obnovit.py (сам стенд — git worktree сайта на коммите выкладки, копия базы
glavpryg_stend, php8.4 -S 127.0.0.1:18090; порядок — log.md 04.11.2026).
Прогон ~/tools/beget/obnovit.py на местной копии хостинга (/tmp/stend-beget):
SFTP и команды — локально в папке стенда, php8.5 → php8.4, расписание не трогается."""
import os, subprocess, sys, types, io
ST = '/tmp/stend-beget'
sys.path.insert(0, os.path.expanduser('~/tools/beget'))

class Fajl(io.FileIO):
    pass

class Sftp:
    def _p(self, p): return os.path.join(ST, p)
    def open(self, p, mode='rb'):
        try: return open(self._p(p), mode)
        except FileNotFoundError as e: raise IOError(str(e))
    def stat(self, p):
        try: return os.stat(self._p(p))
        except FileNotFoundError as e: raise IOError(str(e))
    def mkdir(self, p): os.mkdir(self._p(p))
    def posix_rename(self, a, b): os.replace(self._p(a), self._p(b))
    def remove(self, p): os.remove(self._p(p))

class Kanal:
    def __init__(s, kod): s.kod = kod
    def recv_exit_status(s): return s.kod

class Potok(io.BytesIO):
    def __init__(s, b, kod=0): super().__init__(b); s.channel = Kanal(kod)

class Ssh:
    def open_sftp(self): return Sftp()
    def exec_command(self, cmd, timeout=None):
        r = subprocess.run(cmd.replace('php8.5', 'php8.4'), shell=True, cwd=ST, capture_output=True, timeout=timeout)
        return None, Potok(r.stdout, r.returncode), Potok(r.stderr)

kl = types.ModuleType('kl'); kl.conn = lambda: Ssh(); sys.modules['kl'] = kl
import obnovit as o
o.SAYT = 'http://127.0.0.1:18090'
o.STATUS = '/tmp/stend-status.txt'; o.LOG = '/tmp/stend-obnovlenie.log'
o.snyat_s_raspisaniya = lambda: print('(снятие с расписания пропущено)')
if len(sys.argv) > 1 and sys.argv[1] == 'slomat':
    # Подставной сбой: после обновления главная не находит ярлык игры — должен быть откат
    o.PRIZNAK = 'такого текста на странице нет'
o.main()
print(open(o.STATUS).read()); print(open(o.LOG).read())
