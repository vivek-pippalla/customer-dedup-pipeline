"""Fixed synthetic word lists used by the seeded data generator."""

FIRST_NAMES = (
    "Aaron", "Aarav", "Aditi", "Aisha", "Akash", "Alex", "Amara", "Anaya", "Andrew", "Anika",
    "Arjun", "Ava", "Ben", "Benjamin", "Bill", "Caleb", "Cara", "Daniel", "David", "Dev",
    "Ethan", "Fatima", "Grace", "Hannah", "Ibrahim", "Isha", "Jacob", "James", "Jane", "John",
    "Johnny", "Jonathan", "Joseph", "Karan", "Katherine", "Kate", "Kavya", "Liam", "Liz", "Lucas",
    "Maggie", "Margaret", "Meera", "Michael", "Mike", "Nadia", "Neha", "Noah", "Olivia", "Priya",
    "Rahul", "Ravi", "Robert", "Sam", "Sara", "Sophia", "Thomas", "Vikram", "William", "Zara",
)

LAST_NAMES = (
    "Adams", "Agarwal", "Allen", "Anderson", "Baker", "Banerjee", "Bell", "Bennett", "Brown", "Campbell",
    "Carter", "Clark", "Collins", "Cook", "Cooper", "Das", "Davis", "Edwards", "Evans", "Foster",
    "Garcia", "Gupta", "Hall", "Harris", "Hughes", "Jackson", "Johnson", "Jones", "Kapoor", "Khan",
    "Kumar", "Lewis", "Martin", "Mehta", "Miller", "Mitchell", "Moore", "Morgan", "Murphy", "Patel",
    "Perry", "Phillips", "Price", "Reed", "Roberts", "Shah", "Sharma", "Singh", "Smith", "Taylor",
    "Thomas", "Thompson", "Turner", "Walker", "Ward", "Watson", "White", "Williams", "Wilson", "Young",
)

CITIES_AND_POSTCODES = (
    ("Ahmedabad", "380001"), ("Bengaluru", "560001"), ("Bhopal", "462001"), ("Chandigarh", "160017"),
    ("Chennai", "600001"), ("Coimbatore", "641001"), ("Delhi", "110001"), ("Guwahati", "781001"),
    ("Hyderabad", "500001"), ("Indore", "452001"), ("Jaipur", "302001"), ("Kochi", "682001"),
    ("Kolkata", "700001"), ("Lucknow", "226001"), ("Mumbai", "400001"), ("Mysuru", "570001"),
    ("Nagpur", "440001"), ("Patna", "800001"), ("Pune", "411001"), ("Surat", "395001"),
)

STREET_NAMES = (
    "Ashoka", "Birch", "Cedar", "Clover", "Elm", "Fern", "Garden", "Hill", "Jasmine", "Lake",
    "Maple", "Market", "Meadow", "MG", "Oak", "Park", "River", "Rose", "Station", "Willow",
)

NICKNAME_VARIANTS = {
    "John": ("Jon", "Johnny", "Jonathan"),
    "William": ("Bill",),
    "Elizabeth": ("Liz",),
    "Robert": ("Bob",),
    "Katherine": ("Kate",),
    "Margaret": ("Maggie",),
    "Michael": ("Mike",),
    "Benjamin": ("Ben",),
}

ROLE_EMAILS = ("info@example.com", "accounts@example.org", "support@example.net")
EMAIL_DOMAINS = ("example.com", "example.org", "example.net", "mail.invalid")
