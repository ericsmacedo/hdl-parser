# Application Programming Interface (API)

::: hdl_parser
    options:
        members: []


!!! example "Usage is simple"

    ```python
    >>> import hdl_parser

    >>> file = hdl_parser.parse_file("examples/sv/adder.sv")
    >>> for module in file.modules:
    ...     print(repr(module.name))
    ...     for param in module.params:
    ...         print("  ", repr(param))
    ...     for port in module.ports:
    ...         print("  ", repr(port))
    ...     for port in module.localparams:
    ...         print("  ", repr(port))
    ...     for inst in  module.insts:
    ...         print("   Module:", inst.module, inst.name)
    ...         for con in inst.connections:
    ...             print("    ", con.port, con.con, con.comment)
    'adder'
       Param(id='adder.DATA_WIDTH', ptype='integer', name='DATA_WIDTH', dim='', dim_unpacked='', default='8', ifdefs=(), comment=('Width of input operands',), loc=Location(line=4, col=3, end_line=4, end_col=35, macro=''))
       Param(id='adder.OUTPUT_WIDTH', ptype='integer', name='OUTPUT_WIDTH', dim='', dim_unpacked='', default='4', ifdefs=(), comment=('Test configuration value',), loc=Location(line=5, col=3, end_line=5, end_col=37, macro=''))
       Port(id='adder.A', direction='input', ptype='logic', dtype='unsigned', name='A', dim='[DATA_WIDTH-1:0]', dim_unpacked='', default='', ifdefs=(), comment=('Packed input operand A',), loc=Location(line=7, col=3, end_line=7, end_col=43, macro=''))
       Port(id='adder.B', direction='input', ptype='logic', dtype='unsigned', name='B', dim='[DATA_WIDTH-1:0]', dim_unpacked='', default='', ifdefs=(), comment=('Packed input operand B',), loc=Location(line=8, col=3, end_line=8, end_col=43, macro=''))
       Port(id='adder.X', direction='output', ptype='logic', dtype='unsigned', name='X', dim='[DATA_WIDTH:0]', dim_unpacked='', default='', ifdefs=(), comment=('Packed sum output',), loc=Location(line=9, col=3, end_line=9, end_col=43, macro=''))
       Port(id='adder.byte_p', direction='input', ptype='logic', dtype='', name='byte_p', dim='[7:0]', dim_unpacked='', default='', ifdefs=(), comment=('Packed byte input',), loc=Location(line=10, col=3, end_line=10, end_col=48, macro=''))
       Port(id='adder.word_p', direction='input', ptype='logic', dtype='', name='word_p', dim='[3:0][7:0]', dim_unpacked='', default='', ifdefs=(), comment=('Packed 32-bit word (4 bytes)',), loc=Location(line=11, col=3, end_line=11, end_col=48, macro=''))
       Port(id='adder.flag_u', direction='input', ptype='logic', dtype='', name='flag_u', dim='', dim_unpacked='', default='', ifdefs=(), comment=('Unpacked single bit',), loc=Location(line=12, col=3, end_line=12, end_col=48, macro=''))
       Port(id='adder.arr_u', direction='input', ptype='logic', dtype='', name='arr_u', dim='[7:0]', dim_unpacked='[0:3]', default='', ifdefs=(), comment=('Unpacked byte array',), loc=Location(line=13, col=3, end_line=13, end_col=53, macro=''))
       Param(id='adder.SUM_WIDTH', ptype='', name='SUM_WIDTH', dim='', dim_unpacked='', default='DATA_WIDTH + 1', ifdefs=(), comment=(), loc=Location(line=16, col=3, end_line=16, end_col=41, macro=''))
       Module: test_module u_test_module
         test_input a_port ('Connected to a_port',)
         test_output b_port ('Connected to b_port',)

    ```

See [Datamodel](./api-datamodel.md) for a full reference.
