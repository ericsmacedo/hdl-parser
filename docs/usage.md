# Usage

There are two major use-cases:

* **Command Line**: See [Command Line Interface](cli.md)
* **Python**: See [API](api.md)

## Command Line Examples

### Markdown

!!! example "Generate Markdown Table"

    ```bash
    sv-simpleparser info examples/adder.sv > examples/adder.md
    ```

??? info "Markdown Table Code"

    ``` title="examples/adder.md"
    --8<-- "examples/adder.md"
    ```

??? info "Markdown Table"

    {%
        include-markdown "../examples/adder.md"
    %}

### JSON

!!! example "Generate JSON"

    ```bash
    sv-simpleparser json examples/adder.sv > examples/adder.json
    ```

??? info "JSON File"

    ``` title="examples/adder.json"
    --8<-- "examples/adder.json"
    ```
