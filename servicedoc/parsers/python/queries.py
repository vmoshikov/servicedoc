QUERY_FUNCTIONS = """
(function_definition
  name: (identifier) @func.name
  parameters: (parameters) @func.params
  return_type: (type)? @func.return)
"""

QUERY_CLASSES = """
(class_definition
  name: (identifier) @class.name
  superclasses: (argument_list)? @class.bases
  body: (block) @class.body)
"""

QUERY_DOCSTRINGS_FUNC = """
(function_definition
  body: (block
    (expression_statement
      (string) @docstring)))
"""

QUERY_DOCSTRINGS_CLASS = """
(class_definition
  body: (block
    (expression_statement
      (string) @docstring)))
"""

QUERY_IMPORTS_FROM = """
(import_from_statement
  module_name: (_) @import.module
  name: (dotted_name) @import.name)
"""

QUERY_IMPORTS = """
(import_statement
  name: (dotted_name) @import.name)
"""

QUERY_DECORATORS = """
(decorated_definition
  (decorator) @decorator
  definition: (function_definition
    name: (identifier) @func.name))
"""
