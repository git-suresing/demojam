import streamlit as st
import ollama

# Import sub-agent modules
import ocpabi.abi_agent
import bastion.bastion_agent

st.set_page_config(
    page_title="AI-ChatBot for OpenShift Cluster Orchestrator", 
    page_icon="🎛️", 
    layout="wide"
)

# ==========================================
# 1. AI ROUTING FUNCTION (OLLAMA)
# ==========================================
def get_ai_routing_decision(prompt_text):
    """
    Passes the user's text to local Ollama LLM to determine the correct workflow.
    """
    system_instruction = """
    You are a strict orchestrator routing agent. You must classify the user's CORE INTENT, not just keyword presence. 
    Read the entire prompt. If the user's primary goal is not explicitly to execute one of the pipelines below, output UNKNOWN.
    
    Respond with EXACTLY ONE word from this list (no punctuation, no explanation):
    - ABI : The user explicitly wants to start Agent-Based Installation (ABI).
    - BASTION : The user explicitly wants to start bastion configuration (BASTION).
    - IPI : The user explicitly wants to start Installer Provisioned Infrastructure (IPI).
    - NMSTATE : The user explicitly wants to generate or modify nmstate networking configurations.
    - NRHO : The user explicitly wants to generate or modify an NRHO config file.
    - UNKNOWN : The user is asking a general question, using greeting words, or the core intent does not match the above.
    """

    try:
        response = ollama.chat(
            model='qwen2.5-coder:7b', 
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt_text}
            ],
            options={"temperature": 0.0} 
        )
        
        # Clean up response string (remove whitespace/punctuation)
        raw_decision = response['message']['content'].strip().upper()
        raw_decision = "".join(c for c in raw_decision if c.isalnum())
        
        # ANTI-HALLUCINATION SAFEGUARD
        valid_routes = ["ABI", "IPI", "NMSTATE", "NRHO", "BASTION"]
        if raw_decision in valid_routes:
            return raw_decision
        else:
            return "UNKNOWN"
            
    except Exception as e:
        st.error(f"Error communicating with Ollama: {str(e)}")
        return "UNKNOWN"


# ==========================================
# 2. STATE INITIALIZATION & CLEANUP
# ==========================================
def reset_sub_agent_states():
    """Resets UI and pipeline flags when switching between workflows to prevent UI overlap."""
    st.session_state.pipeline_completed = False
    st.session_state.show_ai_deploy = False
    st.session_state.playbook_generated = False

if "global_workflow" not in st.session_state:
    st.session_state.global_workflow = "HOME"

if "messages" not in st.session_state:
    st.session_state.messages = [
        {
            "role": "assistant", 
            "content": (
                "Hello! Please provide a prompt to start. For example, type:\n"
                "* *'start ocp installation through ABI'*\n"
                "* *'configure bastion node'*\n"
                "* *'I want to deploy nrho'*\n"
                "* *'generate nmstate config file'*"
            )
        }
    ]


# ==========================================
# 3. HOME MENU / AI ROUTER INTERFACE
# ==========================================
if st.session_state.global_workflow == "HOME":
    st.title("🎛️ AI-ChatBot for Cloud Operations")
    st.divider()
    
    # Display previous chat messages
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    # Accept user input
    user_prompt = st.chat_input("Enter your prompt here (e.g., 'start ocp installation through ABI')...")
    
    if user_prompt:
        # Reset chat history per turn to keep clean interface
        st.session_state.messages = []
        
        st.session_state.messages.append({"role": "user", "content": user_prompt})
        with st.chat_message("user"):
            st.markdown(user_prompt)
            
        with st.chat_message("assistant"):
            with st.spinner("Chatbot thinking on your request..."):
                ai_decision = get_ai_routing_decision(user_prompt)
            
            if ai_decision == "ABI":
                msg = "Intent recognized: Initializing the ABI deployment pipeline..."
                st.session_state.messages.append({"role": "assistant", "content": msg})
                st.markdown(msg)
                reset_sub_agent_states()
                st.session_state.global_workflow = "ABI"
                st.rerun()

            elif ai_decision == "BASTION": 
                msg = "Intent recognized: Initializing the Bastion configuration pipeline..."
                st.session_state.messages.append({"role": "assistant", "content": msg})
                st.markdown(msg)
                reset_sub_agent_states()
                st.session_state.global_workflow = "BASTION"
                st.rerun()

            elif ai_decision == "IPI": 
                msg = "Intent recognized: Initializing the IPI Baremetal pipeline..."
                st.session_state.messages.append({"role": "assistant", "content": msg})
                st.markdown(msg)
                reset_sub_agent_states()
                st.session_state.global_workflow = "IPI"
                st.rerun()
                
            elif ai_decision == "NMSTATE":
                msg = "Intent recognized: Initializing the NMState generation pipeline..."
                st.session_state.messages.append({"role": "assistant", "content": msg})
                st.markdown(msg)
                reset_sub_agent_states()
                st.session_state.global_workflow = "NMSTATE"
                st.rerun()

            elif ai_decision == "NRHO":
                msg = "Intent recognized: Initializing the NRHO generation pipeline..."
                st.session_state.messages.append({"role": "assistant", "content": msg})
                st.markdown(msg)
                reset_sub_agent_states()
                st.session_state.global_workflow = "NRHO"
                st.rerun()
                
            else: # Catches "UNKNOWN" or fallback errors
                msg = (
                    "🚨 **Error:** I didn't recognize a supported workflow in your request. "
                    "Please try asking specifically for **ABI**, **BASTION**, **IPI**, **NMSTATE**, or **NRHO**."
                )
                st.session_state.messages.append({"role": "assistant", "content": msg})
                st.markdown(msg)

# ==========================================
# 4. ROUTE TO EXTERNAL SUB-AGENTS
# ==========================================
else:
    # Navigation header button
    if st.button("⬅️ Return to AI Chat"):
        st.session_state.global_workflow = "HOME"
        reset_sub_agent_states()
        st.session_state.messages = [
            {
                "role": "assistant", 
                "content": (
                    "Hello! Please provide a prompt to start. For example, type:\n"
                    "* *'start ocp installation through ABI'*\n"
                    "* *'configure bastion node'*\n"
                    "* *'I want to deploy nrho'*\n"
                    "* *'generate nmstate config file'*"
                )
            }
        ]
        st.rerun()
        
    st.divider()

    # Route exclusively to the active sub-agent module
    if st.session_state.global_workflow == "ABI":
        ocpabi.abi_agent.main()

    elif st.session_state.global_workflow == "BASTION":
#        if hasattr(bastion.bastion_agent, "main"):
        bastion.bastion_agent.main()
#        elif hasattr(bastion.bastion_agent, "run_bastion_agent_workflow"):
#            bastion.bastion_agent.run_bastion_agent_workflow()
#        else:
#            st.error("❌ Bastion module loaded but entrypoint function not found.")

    elif st.session_state.global_workflow == "IPI":
        st.info("ℹ️ IPI Workflow coming soon...")
        
    elif st.session_state.global_workflow == "NMSTATE":
        st.info("ℹ️ NMSTATE Workflow coming soon...")

    elif st.session_state.global_workflow == "NRHO":
        st.info("ℹ️ NRHO Workflow coming soon...")