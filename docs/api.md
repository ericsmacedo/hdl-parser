# Application Programming Interface (API)

::: hdl_parser
    options:
        members: []


!!! example "Usage is simple"

    ```python
    >>> import hdl_parser

    >>> file = hdl_parser.parse_file("examples/adder.sv")
    >>> for module in file.modules:
    ...     print(repr(module.name))
    ...     for param in module.params:
    ...         print("  ", repr(param))
    ...     for port in module.ports:
    ...         print("  ", repr(port))
    ...     for inst in  module.insts:
    ...         print("   Module:", inst.module, inst.name)
    ...         for con in inst.connections:
    ...             print("    ", con.port, con.con, con.comment)
    'adder'
       Param(ptype='integer', name='DATA_WIDTH', dim='', dim_unpacked='', default='8', ifdefs=(), comment=('Width of input operands',))
       Param(ptype='integer', name='OUTPUT_WIDTH', dim='', dim_unpacked='', default='4', ifdefs=(), comment=('Test configuration value',))
       Port(direction='input', ptype='logic', dtype='unsigned', name='A', dim='[DATA_WIDTH-1:0]', dim_unpacked='', ifdefs=(), comment=('Packed input operand A',))
       Port(direction='input', ptype='logic', dtype='unsigned', name='B', dim='[DATA_WIDTH-1:0]', dim_unpacked='', ifdefs=(), comment=('Packed input operand B',))
       Port(direction='output', ptype='logic', dtype='unsigned', name='X', dim='[DATA_WIDTH:0]', dim_unpacked='', ifdefs=(), comment=('Packed sum output',))
       Port(direction='input', ptype='logic', dtype='', name='byte_p', dim='[7:0]', dim_unpacked='', ifdefs=(), comment=('Packed byte input',))
       Port(direction='input', ptype='logic', dtype='', name='word_p', dim='[3:0][7:0]', dim_unpacked='', ifdefs=(), comment=('Packed 32-bit word (4 bytes)',))
       Port(direction='input', ptype='logic', dtype='', name='flag_u', dim='', dim_unpacked='', ifdefs=(), comment=('Unpacked single bit',))
       Port(direction='input', ptype='logic', dtype='', name='arr_u', dim='[7:0]', dim_unpacked='[0:3]', ifdefs=(), comment=('Unpacked byte array',))
       Module: test_module u_test_module
         test_input a_port ('Connected to a_port',)
         test_output b_port ('Connected to b_port',)

    ```

See [Datamodel](./api-datamodel.md) for a full reference.
