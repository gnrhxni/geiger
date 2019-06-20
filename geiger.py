import io
import sys
import wave
import math
import time
import logging
import asyncio
import argparse
import asyncio.streams
from itertools import count

"""read lines from stdin, create a simple webapp that encodes clicks
into audio based off lines from stdin"""


SAMPLE_RATE = 44100
class Click:
    LENGTH = 0.01
    FREQ = 65 # Hz


class Messages:
    _500 = (b'HTTP/1.1 500 Internal Server Error\r\n'+
            b'Content-Type: text/html; charset=utf-8\r\n'+
            b'Content-Length: 0\r\n\r\n')

    _404 = (b'HTTP/1.1 404 Not Found\r\n'+
            b'Content-Type: text/html; charset=utf-8\r\n'+
            b'Content-Length: 0\r\n\r\n')

    main = lambda s: (b'HTTP/1.1 200 OK\r\n'+
            b'Content-Type: text/html; charset=utf-8\r\n'+
            b'Content-Length: '+str(len(s)).encode()+b'\r\n\r\n'+
            s)

    audio_start = (b'HTTP/1.1 200 OK\r\n'+
                   b'Content-Type: audio/wav\r\n\r\n')


with open('index.html', 'rb') as f:
    Messages.main = Messages.main(f.read())

def gen_click():
    size = int(SAMPLE_RATE * Click.LENGTH)
    ret = bytearray(size)
    for i in range(size):
        t = (float(i)/SAMPLE_RATE) * (2*math.pi)
        ret[i] = int(8 * math.sin(Click.FREQ * t)) + 128
    return ret


audiostate = {
    'waveform': None,
    'time': None
}
click = gen_click()
events = []
writer_ids = count()

def new_audio_chunk():
    events.clear()
    audiostate['waveform'] = bytearray(SAMPLE_RATE)
    audiostate['time'] = time.time()


def _stdin_read_handler():
    logging.debug('Handling stdin read')
    sys.stdin.readline()
    events.append((time.time(), None))
    logging.debug('Finished handling stdin read')


def get_raw():
    w = audiostate['waveform']
    t = audiostate['time']
    for event_time, n_events in events:
        idx = int((event_time - t)*SAMPLE_RATE)
        w[idx:idx+len(click)] = click # TODO modulate amplitude based off n_events
    return w

def get_wav():
    w = get_raw()
    fp = io.BytesIO()
    waveobj = wave.open(fp,mode='wb')
    waveobj.setnchannels(1)
    waveobj.setframerate(SAMPLE_RATE )
    waveobj.setsampwidth(1)
    waveobj.setcomptype('NONE','NONE')
    waveobj.writeframes(w)
    val = fp.getvalue()
    waveobj.close()
    return val


def handle_quick_pages(line):
    try:
        uri = line.rsplit(b' ', 1)[0].split(b' ', 1)[1]
    except IndexError:
        return Messages._500

    if uri == b'/':
        return Messages.main
    if uri == b'/audio.wav':
        return 'wav'
    if uri == b'/audio.raw':
        return 'raw'
    else:
        return Messages._404


async def handle_http_get(reader, writer):
    logging.debug("Handling web request")
    line = await reader.readuntil(b'\r\n')
    msg = handle_quick_pages(line)
    if msg in ('wav', 'raw'):
        writer_id = next(writer_ids)
        writer.write(Messages.audio_start)
        while True:
            start_time = time.time()
            logging.debug('Looping for long connection. ')
            logging.debug('Generating one second of audio')
            data = get_wav() if msg == 'wav' else get_raw()
            logging.debug('Generated')
            writer.write(data)
            try:
                await writer.drain()
            except ConnectionResetError:
                break
            logging.debug('written')
            new_audio_chunk()
            logging.debug('refreshed audio chunk')
            await asyncio.sleep(max(0, 1.-(time.time() - start_time)))

    else:
        writer.write(msg)
        logging.debug("closing short connection")
        await writer.drain()
        writer.close()


async def main(host, port):
    new_audio_chunk()
    loop = asyncio.get_event_loop()
    loop.add_reader(sys.stdin.fileno(), _stdin_read_handler)
    server = await asyncio.start_server(handle_http_get, host, port, loop=loop)
    addr = server.sockets[0].getsockname()
    logging.info('Serving on %s', addr)
    return server
    

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(created)f %(levelname)s %(message)s')
    parser = argparse.ArgumentParser(description='Click when a line is read from stdin.')
    parser.add_argument('--host', help='IP address to bind to and serve the webapp.',
                        default='0.0.0.0')
    parser.add_argument('--port', type=int, default=9099,
                        help='What port should I use to serve the webapp?')

    args = parser.parse_args()
    loop = asyncio.get_event_loop()
    server = loop.run_until_complete(main(args.host, args.port))
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        pass

    # Close the server
    server.close()
    loop.run_until_complete(server.wait_closed())
    loop.close()
