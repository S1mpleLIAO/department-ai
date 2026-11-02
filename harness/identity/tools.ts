import {defineTool} from '/opt/harness/packages/core/tools/src/index.ts';
import fs from 'node:fs/promises';
import path from 'node:path';
export const inject=['tools','skills'];
const entries=[
 ['department_context_get','每个部门任务开始前读取最新助手定位、工作原则、回答默认项和获准工具',{}],
 ['department_processes','查看当前空间可用的正式业务流程',{}],
 ['department_knowledge_search','检索有权限的已发布知识和模板',{query:{type:'string',required:true}}],
 ['department_document_get','读取检索结果中的已发布文档正文',{id:{type:'string',required:true}}],
 ['department_skill_list','列出有使用权限的已审核发布技能',{}],
 ['department_skill_get','读取已发布技能说明或指定资源；先读取完整说明再按要求工作',
  {id:{type:'string',required:true},resource:{type:'string'}}],
 ['department_skill_prepare','将已发布技能完整资源准备到个人工作区供本地执行；需要使用及源码权限，不修改正式技能。报销优先使用专用生成工具。',{id:{type:'string',required:true}}],
 ['department_uploaded_document_read','读取本次上传材料正文（PDF/Office/文本）；传入附件展示的完整 /home/assistant/dsh/attachments/v1/files/... 路径',{path:{type:'string',required:true}}],
 ['department_reimbursement_generate','执行已发布报销技能生成待审核 Word 文件。先读取技能说明、原始票据；缺项先询问，不能猜金额。jobJson 按技能示例且各次出差必填项目/城市/起止日期/接待单位/事项/交通方式和四组票据明细；profileJson 含姓名、部门、职务、银行卡、开户行五个字符串。返回可点击下载链接。',
  {jobJson:{type:'string',required:true},profileJson:{type:'string',required:true}}],
] as const;
async function call(name:string,args:any,signal?:AbortSignal){
  const response=await fetch('http://127.0.0.1:39100/tool/'+name,{
    method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(args),
    signal:signal ? AbortSignal.any([signal,AbortSignal.timeout(30000)]) :
      AbortSignal.timeout(name==="department_reimbursement_generate"?200000:name==="department_uploaded_document_read"?650000:30000)});
  if(!response.ok){const error=await response.json().catch(()=>({}));throw Error(error.detail||('部门工具失败；HTTP '+response.status));}
  return response.json();
}

// Native Skill provider uses the same live authorization checks as departmental tools.
// No shared filesystem roots and no user-authored files are advertised as approved skills.
export function apply(ctx:any){
  ctx.skills.registerProvider(()=>({
    name:'department-published',
    async list(options:any){
      const context=await call('department_context_get',{},options.signal);
      if(!context.availableTools.includes('department_skill_list'))return [];
      const items=await call('department_skill_list',{},options.signal);
      return items.map((item:any)=>({name:item.name,description:item.description,rank:0,
        source:'custom',provider:'department-published',locator:item.id,
        invocation:{modelInvocable:true,userInvocable:true},
        resourceBase:{kind:'opaque',description:'通过 department_skill_get 读取资源；需要本地运行且有源码权限时使用 department_skill_prepare。'}}));
    },
    async get(candidate:any,options:any){
      const skill=await call('department_skill_get',{id:candidate.locator},options.signal);
      return {...candidate,content:skill.instructions+'\n\n技能ID：'+candidate.locator+
        '\n获准资源需通过 department_skill_get 按相对路径读取：'+JSON.stringify(skill.resources)+
        '\n报销使用 department_reimbursement_generate；其他脚本需使用 department_skill_prepare 准备到个人工作区后执行（需源码权限）。不能直接读取共享目录。'};
    },
  }));
  for(const [name,description,parameters] of entries)ctx.tools.register(defineTool({
    name,description,parameters,
    output:{schema:{type:'object',additionalProperties:false,properties:{text:{type:'string',required:true}}},
      render:(_args:any,value:any)=>[{type:'text',text:value.text}]},
    async execute(args:any){
      const value=await call(name,args);
      if(name!=='department_skill_prepare')return {text:JSON.stringify(value)};
      const directory=await fs.mkdtemp('/home/assistant/workspace/skill-');
      try {
        const resources=value.resources||[];
        if(resources.length>512)throw Error('技能资源数量超过限制');
        let total=0;
        for(const resource of resources){
          const parts=resource.path.split('/');
          if(!['scripts','references','assets'].includes(parts[0]) || parts.some((x:string)=>!x||x==='.'||x==='..'||/[\\\x00-\x1f]/.test(x)))throw Error('技能资源路径无效');
          const bytes=Buffer.from(resource.contentBase64,'base64');total+=bytes.length;
          if(total>10*1024*1024)throw Error('技能资源超过10 MiB');
          const target=path.join(directory,...parts);
          await fs.mkdir(path.dirname(target),{recursive:true,mode:0o700});
          await fs.writeFile(target,bytes,{mode:0o600,flag:'wx'});
        }
        await fs.writeFile(path.join(directory,'SKILL.md'),value.skill.instructions,{mode:0o600,flag:'wx'});
        return {text:JSON.stringify({directory,resources:resources.map((r:any)=>r.path),
          message:'个人工作副本已准备。按完整技能说明执行，正式发布版本未修改；下载输出请放在个人工作区。'})};
      } catch(error){await fs.rm(directory,{recursive:true,force:true});throw error;}

    },
    presentCall:(args:any)=>({card:'generic',title:description,kind:'other',rawInput:args}),
  }));
}
