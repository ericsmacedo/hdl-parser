## Module `param_module`

Path `EXAMPLES/param_module.sv`

### Parameters
                                                                           
| Name               | Dimension   | Default  | Functional Description    |
|--------------------|-------------|----------|---------------------------|
| `WIDTH`            |             | `8`      | Width of the input data   |
| `DEPTH`            |             | `4`      |                           |
| `INIT_VAL`         | `[7:0]`     | `8'hFF`  |                           |
| `ENABLE_FEATURE`   |             | `1'b1`   |                           |
                                                                           
### Ports
                                                                           
| Name          | Dimension       | I/O        | Functional Description   |
|---------------|-----------------|------------|--------------------------|
| `clk`         | `1`             | `input`    |                          |
| `rst_n`       | `1`             | `input`    | active-low reset         |
| `data_in`     | `[WIDTH-1:0]`   | `input`    | Input data               |
|               |                 |            | other comment            |
| `data_out`    | `[WIDTH-1:0]`   | `output`   |                          |
| `bidir_bus`   | `[DEPTH-1:0]`   | `inout`    |                          |
                                                                           
## Module `sub_module`

Path `EXAMPLES/param_module.sv`

### Parameters
                                                                           
| Name            | Dimension    | Default   | Functional Description     |
|-----------------|--------------|-----------|----------------------------|
| `DATA_WIDTH`    |              | `8`       |                            |
| `INIT_VALUE`    | `[7:0]`      | `0`       |                            |
                                                                           
### Ports
                                                                           
|               |                      |          | Functional            |
| Name          | Dimension            | I/O      | Description           |
|---------------|----------------------|----------|-----------------------|
| `clk`         | `1`                  | `input`  |                       |
| `reset`       | `1`                  | `input`  |                       |
| `input_data`  | `[DATA_WIDTH-1:0]`   | `input`  |                       |
| `output_data` | `[DATA_WIDTH-1:0]`   | `output` |                       |
| `config_bus`  | `[DATA_WIDTH/2-1:0]` | `inout`  |                       |
                                                                           
