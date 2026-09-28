# Interfaces

<!--
The seams. A shared decision goes here only if two parts could choose incompatibly, the call is not
obvious, and it is a real trade-off. Every change needs a decisions.md entry.
-->

## Dependency direction
<!-- which layer may depend on which; checked by a tool when the project has one -->
- <domain> depends on nothing that does I/O
- <adapters> implement ports and return data, never authority

## Ports
### <PortName>
Shape: <signatures, types, or schema>
Contract test: <path> (owned by M<k>, the milestone that introduces it)
Real adapter: <where> · Test adapter: <where, reachable only from tests>
Failure semantics: <what callers see on each failure>

## Data shapes
<entities, identifiers, lifecycle, deletion>
