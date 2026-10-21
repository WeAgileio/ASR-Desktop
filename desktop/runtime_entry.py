from asr_desktop.runtime import main

if __name__ == "__main__":
    # Route spawned multiprocessing helpers before parsing application arguments.
    # Whisper dependencies may start the resource tracker in frozen execution.
    import multiprocessing
    multiprocessing.freeze_support()
    raise SystemExit(main())
