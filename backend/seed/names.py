"""Synthetic Indian names by region (for demo data only)."""

REGIONS = {
    "tamil": {
        "M": ["Karthik", "Arun", "Vignesh", "Praveen", "Surya", "Dinesh", "Ganesh", "Hari", "Manoj", "Naveen", "Prakash",
              "Rajesh", "Saravanan", "Senthil", "Vijay", "Aravind", "Balaji", "Gokul", "Kishore", "Muthu", "Sathish",
              "Tamilarasan", "Yuvaraj", "Ashwin"],
        "F": ["Priya", "Divya", "Kavya", "Lakshmi", "Meena", "Nandhini", "Pavithra", "Revathi", "Sangeetha", "Swathi",
              "Abinaya", "Deepa", "Gayathri", "Janani", "Keerthana", "Monisha", "Harini", "Sowmya", "Dharani", "Vaishnavi"],
        "S": ["Ramasamy", "Subramanian", "Krishnan", "Murugan", "Natarajan", "Palanisamy", "Rajendran", "Selvam",
              "Shanmugam", "Velu", "Kandasamy", "Arumugam", "Senthil", "Mani", "Ravi", "Sekar"],
    },
    "hindi": {
        "M": ["Rahul", "Amit", "Ankit", "Rohit", "Vikas", "Saurabh", "Abhishek", "Aditya", "Deepak", "Gaurav", "Manish",
              "Nikhil", "Pankaj", "Rajat", "Sachin", "Vivek", "Shubham", "Akash", "Harsh", "Kunal"],
        "F": ["Pooja", "Neha", "Anjali", "Shivani", "Priyanka", "Kajal", "Komal", "Nidhi", "Riya", "Sakshi", "Shruti",
              "Swati", "Aarti", "Khushi", "Muskan", "Tanya"],
        "S": ["Sharma", "Verma", "Gupta", "Singh", "Yadav", "Mishra", "Tiwari", "Pandey", "Chauhan", "Agarwal",
              "Srivastava", "Dubey", "Meena", "Jain", "Saxena", "Kushwaha"],
    },
    "west": {
        "M": ["Aniket", "Omkar", "Pratik", "Sagar", "Tushar", "Yash", "Harsh", "Parth", "Dhruv", "Jay", "Rushikesh",
              "Siddharth", "Chirag", "Nirav"],
        "F": ["Sneha", "Pranali", "Rutuja", "Shraddha", "Aishwarya", "Hetal", "Krupa", "Mansi", "Sayali", "Dhwani",
              "Komal", "Payal"],
        "S": ["Patil", "Deshmukh", "Kulkarni", "Jadhav", "Pawar", "Shinde", "Joshi", "Patel", "Shah", "Desai", "Mehta",
              "Chaudhari", "Gaikwad", "Trivedi"],
    },
    "telugu": {
        "M": ["Sai", "Venkatesh", "Srinivas", "Charan", "Harsha", "Teja", "Mahesh", "Ravi", "Pavan", "Kalyan", "Naresh",
              "Vamsi"],
        "F": ["Sravani", "Bhavani", "Harika", "Keerthi", "Lavanya", "Mounika", "Sirisha", "Tejaswini", "Pallavi", "Divya"],
        "S": ["Reddy", "Rao", "Naidu", "Chowdary", "Varma", "Goud", "Raju", "Yadav"],
    },
    "kannada": {
        "M": ["Darshan", "Kiran", "Manjunath", "Prajwal", "Shreyas", "Chetan", "Rakesh", "Sudeep", "Nagaraj", "Pradeep"],
        "F": ["Ananya", "Bhoomika", "Chaitra", "Rakshitha", "Spoorthi", "Kavana", "Shwetha", "Vidya", "Megha"],
        "S": ["Gowda", "Hegde", "Shetty", "Rao", "Kamath", "Bhat", "Naik", "Patil"],
    },
    "kerala": {
        "M": ["Akhil", "Arjun", "Jithin", "Nithin", "Sreejith", "Vishnu", "Abhijith", "Rahul", "Anand"],
        "F": ["Anju", "Athira", "Aswathy", "Lekshmi", "Sreelakshmi", "Gopika", "Neethu", "Reshma"],
        "S": ["Nair", "Menon", "Pillai", "Kurup", "Thomas", "Varghese", "Joseph", "Kumar"],
    },
    "bengali": {
        "M": ["Arnab", "Soumya", "Subhajit", "Rohan", "Debashish", "Sayan", "Anirban", "Pritam"],
        "F": ["Ankita", "Moumita", "Rimpa", "Sayani", "Tanushree", "Debolina", "Payel", "Srija"],
        "S": ["Banerjee", "Chatterjee", "Das", "Ghosh", "Mukherjee", "Roy", "Sen", "Bose", "Dutta"],
    },
}

STATE_REGION = {"TN": "tamil", "MH": "west", "GJ": "west", "KA": "kannada", "AP": "telugu", "TS": "telugu",
                "UP": "hindi", "MP": "hindi", "RJ": "hindi", "DL": "hindi", "KL": "kerala", "WB": "bengali"}
