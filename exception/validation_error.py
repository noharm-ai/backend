class ValidationError(Exception):
    def __init__(self, message, code, httpStatus):
        super().__init__(message)
        
        self.code = code
        self.httpStatus = httpStatus