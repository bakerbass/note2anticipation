import time
import subprocess
import os
import threading
from pythonosc.dispatcher import Dispatcher
from pythonosc import osc_server, udp_client
from watcher import watch_directory
from model_loader import load_model
from midi_utils import validate_midi_file, get_total_bars, save_midi_file
from anti import inpaint, continuation
import synth
from send_midi_osc import send_midi
from chords import MIDI_Stream
import chords
from melody import rule_based_melody
def open_neuralnote(app_path):
    try:
        subprocess.Popen(["open", app_path])
        print(f"Opened NeuralNote at : {app_path}")
    except Exception as e:
        print(f"Failed to open NeuralNote: {e}")

file_count = 0

def midi_to_liveosc(file_path, segmented_sends=False, input_offset=0):
    global midi_file_count, midi_file_path

    if not validate_midi_file(file_path):
        return

    midi_file_path = file_path
    
    if (segmented_sends):
        midi_file_path = file_path
        if midi_file_count == 0:
            print("First file being sent! File path:" + file_path + " | File no. " + str(midi_file_count))
            # First file: send immediately with fire_immediately False and no offset.
            send_midi(client, file_path, fire_immediately=True, time_offset=8)
            midi_file_count += 1
        elif midi_file_count == 1:
            print("Second file being sent! File path:" + file_path + " | File no. " + str(midi_file_count))
            # Second file: send to same track/clip as first file, but offset by one bar (e.g. 4 beats).
            client.send_message("/live/clip/fire", [0, 0])
            send_midi(client, file_path, fire_immediately=False, time_offset=12, file_idx=1)
            midi_file_count += 1
        else:
            print("Subsequent file being sent! File path:" + file_path + " | File no. " + str(midi_file_count))
            send_midi(client, file_path, fire_immediately=False, clip_index=midi_file_count-1, file_idx=midi_file_count)
    else:
        send_midi(client, file_path, fire_immediately=True, time_offset=input_offset)
    interact() # melody, continuation, send continuation to liveosc
    return midi_file_path
def anti_to_liveosc(file_path, clip_index=1):
    if not validate_midi_file(file_path):
        return
    send_midi(client, file_path, fire_immediately=False, clip_index=clip_index)
def midi_to_GB_UDP(midi_file_path):
    midi_stream = MIDI_Stream(midi_file_path)

    chords, strum, pluck, full_chords = midi_stream.get_UDP_lists()
    chords_list = [list(item) for item in chords]
    strum_list = [list(item) for item in strum]
    pluck_list = [list(item) for item in pluck]
    print(chords_list)
    print(strum_list)

    pluck_message, melody_path = rule_based_melody(full_chords)
    # pluck_message = [[note (midi value), duration, speed, timestamp]]

    client.send_message("/Chords", chords_list)
    client.send_message("/Strum", strum_list)
    client.send_message("/Pluck", pluck_list)
    
def watch_NN_dir(input_directory):
    watch_directory(input_directory, midi_to_liveosc)

def watch_Anti_dir(input_directory):
    watch_directory(input_directory, anti_to_liveosc)

def start_server(ip, port):
    dispatcher = Dispatcher()
    dispatcher.map("/live/error", print_error)
    dispatcher.map("/live/clip/get/playing_position", playing_position_handler)
    server = osc_server.ThreadingOSCUDPServer((ip, port), dispatcher)
    print("Serving on {}".format(server.server_address))
    server.serve_forever()

def print_error(address, args):
    print("Received error from Live: %s" % args)

playing_position = -1.0

def playing_position_handler(address, *args):
    global playing_position
    playing_position = args[2]  # assumes a single float value is sent

midi_file_path = None
model = None
neuralnote_path = "../NeuralNote/build/NeuralNote_artefacts/Release/Standalone/NeuralNote.app/"  # Path to NeuralNote
model_size = 'small'
def chord_continuation(file_path, anti_dir):
    global model
    if not model:
        print("Model not loaded. Please load a model first.")
        return
    new_acc = continuation(file_path, model, 16, time_unit='bars', debug=True, viz=False)
    save_midi_file(new_acc, anti_dir + "/continuation.mid")

def continue_and_send():
    cont = continuation(midi_file_path, model, 16, time_unit='bars', debug=True, viz=False)
    save_midi_file(cont, Anti_dir + "/continuation.mid")
    anti_to_liveosc(Anti_dir + "/continuation.mid")

def interact():
    threading.Thread(target=continue_and_send, daemon=True).start()
    client.send_message("/live/clip/start_listen/playing_position", [0,0])
    while playing_position < 60.0:
        time.sleep(1)
    # print("Moving on! Playing position: ", playing_position)
    midi_stream = MIDI_Stream(midi_file_path)
    chords, strum, pluck, full_chords = midi_stream.get_UDP_lists()
    melody_path = rule_based_melody(full_chords)
    send_midi(client, melody_path, fire_immediately=True, track_index=1)

if __name__ == "__main__":
    print("Hello!")
    print("Starting NeuralNote...")
    # open_neuralnote(neuralnote_path) # commented for vst use
    synth.initialize_fluidsynth()

    NN_dir = "./watcherNN"  # Directory to watch for new MIDI files from neuralnote (or a test directory)
    if not os.path.exists(NN_dir):
        os.makedirs(NN_dir)
    Anti_dir = "./watcherAnti"  # Directory to watch for new MIDI files from Anticipation 
    if not os.path.exists(Anti_dir):
        os.makedirs(Anti_dir)
    
    # Load the model
    print("Loading model...")
    model = load_model(model_size)
    print(f"Model loaded: {model_size}")

    # Start the OSC server in a separate thread
    server_ip = "127.0.0.1"
    server_port = 11001
    server_thread = threading.Thread(target=start_server, args=(server_ip, server_port))
    server_thread.daemon = True
    server_thread.start()

    # Start the OSC client
    client_ip = "127.0.0.1"
    client_port = 11000
    client = udp_client.SimpleUDPClient(client_ip, client_port)

    # Start watching the directory for new MIDI files in a separate thread
    NNWatcher_thread = threading.Thread(target=watch_NN_dir, args=(NN_dir,))
    NNWatcher_thread.daemon = True
    NNWatcher_thread.start()

    AntiWatcher_thread = threading.Thread(target=watch_Anti_dir, args=(Anti_dir,))
    AntiWatcher_thread.daemon = True
    AntiWatcher_thread.start()

    # Wait for a MIDI file to be detected
    while True:
        time.sleep(1)

