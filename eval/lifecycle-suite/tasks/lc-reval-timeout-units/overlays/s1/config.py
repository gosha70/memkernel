class Config:
    _values = {"request_timeout": "2500"}

    @classmethod
    def value(cls, name):
        return cls._values[name]
