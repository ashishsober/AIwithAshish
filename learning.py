from typing import TypedDict, Union
class User(TypedDict):
    name: str
    age: int

user = User(name="Alice", age=30)
print(user)


def square(x: Union[int, float]) -> float:
    return x * x

squared_value = square(x=5)
print(squared_value)

# lambda functions are shortcut to writing smaller functions
new_square = lambda x: x * x
print(new_square(25))
nums = [1, 2, 3, 4, 5]
squared_nums = list(map(lambda x: x * x, nums))
print(squared_nums)


