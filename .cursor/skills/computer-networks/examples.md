# Computer Networks — examples

Patterns for programs in this repo. Adapt names and ports; keep stdin/stdout and printed steps.

## CRC (bit string)

Input: data `1101011011`, generator `10011`.

Print:

- padded message
- each XOR step (or a compact remainder trace)
- remainder / FCS
- transmitted frame

Final line: `Transmitted: <frame>`

## Subnetting

Input: `192.168.10.25/28`

Output shape:

```
IP: 192.168.10.25
Prefix: /28  Mask: 255.255.255.240
Network: 192.168.10.16
Broadcast: 192.168.10.31
Usable: 192.168.10.17 – 192.168.10.30
Hosts: 14
```

## TCP echo (lab pair)

`server.py`: bind `127.0.0.1`, port `5000`, accept one client (or loop), `recv` → `send` same bytes, close.

`client.py`: connect, send a line, print reply.

Run (two terminals):

```
python server.py
python client.py
```

## Stop-and-wait (simulation)

Do not need real loss unless asked. Print per frame:

```
Sender: seq=0 data=...
Receiver: ACK 0
Sender: seq=1 data=...
```

If simulating loss: mark `TIMEOUT` then retransmit the same seq.

## Dijkstra table

For each iteration print: current node, distance vector, previous hop. End with path from source to each destination.

## Hamming encode

Input: data bits. Output: positions table (P1, P2, D1, P4, ...) then the codeword and parity checks.
