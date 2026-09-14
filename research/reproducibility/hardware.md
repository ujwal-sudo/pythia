# Hardware Reproducibility

Record hardware for every training, evaluation, tokenizer, or data-processing run whose timing, memory, throughput, or result could depend on the machine.

Required fields:

- machine/provider
- CPU model and count
- RAM
- GPU model, count, and VRAM
- storage type and available capacity
- accelerator driver versions
- distributed training topology, if any
- measured wall-clock time, when relevant

No hardware-dependent measurements are recorded yet.
