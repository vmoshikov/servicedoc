QUERY_FUNCTIONS = """
(function_declaration
  name: (identifier) @func.name
  parameters: (parameter_list) @func.params
  result: (_)? @func.result)
"""

QUERY_METHODS = """
(method_declaration
  receiver: (parameter_list) @method.receiver
  name: (field_identifier) @method.name
  parameters: (parameter_list) @method.params
  result: (_)? @method.result)
"""

QUERY_STRUCTS = """
(type_declaration
  (type_spec
    name: (type_identifier) @struct.name
    type: (struct_type) @struct.body))
"""

QUERY_INTERFACES = """
(type_declaration
  (type_spec
    name: (type_identifier) @iface.name
    type: (interface_type) @iface.body))
"""

QUERY_IMPORTS = """
(import_spec path: (interpreted_string_literal) @import.path)
"""

QUERY_COMMENTS = """
(comment) @comment
"""

QUERY_STRUCT_FIELDS = """
(field_declaration
  name: (field_identifier_list) @field.name
  type: (_) @field.type
  tag: (raw_string_literal)? @field.tag)
"""
