#!/bin/bash
# Runs build_opinion_map.py (resumes automatically, stops at daily API limit)
cd /Users/luisakaczmarek/data_capstone/Graph_database
source venv/bin/activate
python3 build_opinion_map.py >> build_opinion_map_log.txt 2>&1
