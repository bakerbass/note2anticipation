import sys
import time
import matplotlib.pyplot as plt
import numpy as np
from scipy.io import wavfile
from transformers import AutoModelForCausalLM
from mido import MidiFile, tempo2bpm

from IPython.display import Audio

from anticipation import ops
from anticipation.sample import generate
from anticipation.tokenize import extract_instruments
from anticipation.convert import events_to_midi, midi_to_events
from anticipation.visuals import visualize
from anticipation.config import *
from anticipation.vocab import *
from anticipation.convert import MAX_DUR

from model_loader import load_model
from audio_utils import normalize_wav
from midi_utils import detect_bpm
from datetime import datetime
def inpaint(midi_file_path, start_time, end_time, model, time_unit='bars'):
    bpm = detect_bpm(midi_file_path)
    if bpm is None:
        print("BPM not detected. Using default values.")
        bpm = 120

    beats_per_bar = 4
    seconds_per_beat = 60 / bpm
    seconds_per_bar = beats_per_bar * seconds_per_beat

    if time_unit == 'bars':
        start_time = start_time * seconds_per_bar
        end_time = end_time * seconds_per_bar

    start = time.time()
    events = midi_to_events(midi_file_path)
    end = time.time()
    print("MIDI converted in ", end-start, " seconds")

    segment = events
    segment = ops.translate(segment, -ops.min_time(segment, seconds=False))
    # further work to be done here regarding the control flow and history...
    history = ops.clip(segment, 0, start_time, clip_duration=False)
    anticipated = [CONTROL_OFFSET + tok for tok in ops.clip(segment, start_time + .01, end_time, clip_duration=False)]

    start = time.time()
    inpainted = generate(model, start_time, end_time, inputs=history, controls=anticipated, top_p=.95)
    end = time.time()
    print("Generated in ", end-start, " seconds")
    visualize(inpainted, 'output.png')
    combined = ops.combine(inpainted, anticipated)
    return inpainted, combined

def continuation(midi_file_path, model, length, newlength=None, time_unit='bars', debug=False, viz=False):
    # Outputs a continuation of the input MIDI file.
    bpm = detect_bpm(midi_file_path)
    if bpm is None:
        [print("BPM not detected. Using default values.") if debug else None]
        bpm = 120

    beats_per_bar = 4
    seconds_per_beat = 60 / bpm
    seconds_per_bar = beats_per_bar * seconds_per_beat

    if time_unit == 'bars':
        length = length * seconds_per_bar
        if newlength is not None:
            newlength = newlength * seconds_per_bar

    if newlength is None: # if newlength is not provided, the input length will match the output length (e.g. 16 bars -> 16 new bars)
        newlength = length

    [print("length (in seconds: ", length) if debug else None]
    [print("newlength (in seconds): ", newlength) if debug else None]

    history = midi_to_events(midi_file_path)
    proposal = generate(model, start_time=length, end_time=length+newlength, inputs=history, top_p=.95)
    continuation = ops.clip(proposal, length, length+newlength, clip_duration=False)
    continuation = ops.translate(continuation, -ops.min_time(continuation, seconds=False))
    if (viz):
        visualize(continuation, 'output.png')

    return events_to_midi(continuation)