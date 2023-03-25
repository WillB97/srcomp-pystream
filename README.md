# SRComp HTTP EventStream and WebSocket module

A Python application that gives an EventStream and WebSocket of events from SRComp by wrapping the HTTP API.

## Usage

### Install:

Install the package from Github.
```
pip install git+https://github.com/WillB97/srcomp-pystream.git
```

### Running

Assuming you have [srcomp-http](https://github.com/PeterJCLaw/srcomp-http)
running on `http://localhost:5112/comp-api/`,
run `srcomp-pystream --api-url http://localhost:5112/comp-api/`.

The output from the stream can be seen via curl, for example: curl http://localhost:8080.

## Development

### Install:

Install the package in editable mode.
```
pip install -e .[dev]
```

### Usage

The code can be run the same as above, [srcomp-dev](https://github.com/PeterJCLaw/srcomp-dev)
may be useful for running this in a development environment.

To run linting, ~~type checking~~ and isort again the codebase, run:
```
make check
```

To build wheels, tag the repository with the version and run:
```
make build
```
The generated wheel will be in `dist/`.
