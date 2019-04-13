# 66 Tolls
Alexa skill that gets real-time toll prices for Interstate 66 inside the beltway in Northern Virginia. 
You can try it out on Alexa. The invocation is "Open sixty six tolls."

This skill provides information on the current tolls being charged on I-66 inside the Beltway, 
between the Capital Beltway and the Teddy Roosevelt Bridge. 
        
It also provides end to end speed and travel time information for both I-66 and US-50.  
You can ask for inbound or outbound tolls or inbound or outbound speeds. You can also ask 
for the toll hours or for additional information about the tolls, including the hours.
If you would like Alexa to remember your most frequent inbound or outbound entrance and exit,
you can say save my trip.

It's written in Python 3, using the Alexa Skills kit SDK for Python. It's written for the python code
to run on AWS's lambda service and uses DynamoDB to persist user data. 

The two files are the python file and the intraction model (a JSON file). 
